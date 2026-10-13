using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Net.Sockets;
using System.Text;

namespace ArmadaStardew;

// Only JSON crosses this boundary. All game access stays on SMAPI's game thread.
internal sealed class Link : IDisposable
{
    public readonly ConcurrentQueue<string> Incoming = new();
    private readonly CancellationTokenSource stop = new();
    private readonly object connectionLock = new();
    private readonly int port;
    private TcpClient? connection;
    private Task? worker;
    private string latest = "{\"ready\":false}";
    public Link(int port = 47800) { this.port = port; }
    public void Publish(string json) => Volatile.Write(ref latest, json);
    public void Start(Action<string>? report = null)
    {
        lock (connectionLock)
        {
            if (worker != null) return;
            worker = Task.Run(() => Run(report));
            _ = worker.ContinueWith(t => Report(report, "Second-screen worker stopped: " + t.Exception?.GetBaseException()), TaskContinuationOptions.OnlyOnFaulted);
        }
    }
    public void Dispose()
    {
        stop.Cancel();
        lock (connectionLock) connection?.Close();
    }
    private async Task Run(Action<string>? report)
    {
        bool reportedFailure = false;
        while (!stop.IsCancellationRequested)
        {
            using var client = new TcpClient { NoDelay = true };
            lock (connectionLock)
            {
                if (stop.IsCancellationRequested) return;
                connection = client;
            }
            try
            {
                await client.ConnectAsync("127.0.0.1", port, stop.Token).AsTask().WaitAsync(TimeSpan.FromSeconds(3), stop.Token).ConfigureAwait(false);
                using var stream = client.GetStream();
                using var cancel = CancellationTokenSource.CreateLinkedTokenSource(stop.Token);
                await Send(stream, 1, "{\"appid\":413150,\"provider\":\"stardew-field-journal\"}", cancel.Token).ConfigureAwait(false);
                if (reportedFailure) Report(report, "Second-screen connection restored.");
                reportedFailure = false;
                var reader = Read(stream, cancel.Token);
                try
                {
                    string? previous = null;
                    while (!reader.IsCompleted)
                    {
                        var current = Volatile.Read(ref latest);
                        if (current != previous) { await Send(stream, 3, current, cancel.Token).ConfigureAwait(false); previous = current; }
                        await Task.Delay(100, cancel.Token).ConfigureAwait(false);
                    }
                    await reader.ConfigureAwait(false);
                }
                finally
                {
                    // Closing the socket releases a pending read even if Wine
                    // doesn't complete its cancellation. Cleanup itself is bounded.
                    cancel.Cancel(); client.Close();
                    try { await reader.WaitAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); }
                    catch (Exception) { }
                }
            }
            catch (Exception ex) when (!stop.IsCancellationRequested)
            {
                if (!reportedFailure) Report(report, "Second-screen connection interrupted; retrying: " + ex.GetType().Name + ": " + ex.Message);
                reportedFailure = true;
            }
            catch (Exception) when (stop.IsCancellationRequested) { }
            finally
            {
                lock (connectionLock) if (ReferenceEquals(connection, client)) connection = null;
                client.Close();
            }
            try { await Task.Delay(1500, stop.Token).ConfigureAwait(false); }
            catch (OperationCanceledException) { break; }
        }
    }
    private async Task Read(NetworkStream stream, CancellationToken token)
    {
        var header = new byte[16];
        while (true)
        {
            // An idle host is valid. Once any packet arrives, the rest of its
            // header and body must finish promptly or reconnect from a clean frame.
            int first = await stream.ReadAsync(header.AsMemory(0, 1), token).ConfigureAwait(false);
            if (first == 0) throw new EndOfStreamException();
            using var message = CancellationTokenSource.CreateLinkedTokenSource(token);
            message.CancelAfter(2000);
            await Fill(stream, header.AsMemory(1), message.Token).ConfigureAwait(false);
            if (Encoding.ASCII.GetString(header, 0, 4) != "A2SS") throw new IOException("Invalid header");
            int length = BinaryPrimitives.ReadInt32LittleEndian(header.AsSpan(8));
            if (length < 0 || length > 65536) throw new IOException("Invalid message size");
            var body = new byte[length]; await Fill(stream, body, message.Token).ConfigureAwait(false);
            if (BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(4)) == 16 && Incoming.Count < 32)
                Incoming.Enqueue(Encoding.UTF8.GetString(body));
        }
    }
    private static void Report(Action<string>? report, string message)
    {
        try { report?.Invoke(message); }
        catch { /* A logging failure must not stop the reconnect worker. */ }
    }
    private static async Task Fill(NetworkStream stream, Memory<byte> bytes, CancellationToken token)
    {
        int offset = 0;
        while (offset < bytes.Length)
        {
            int count = await stream.ReadAsync(bytes[offset..], token).AsTask().WaitAsync(token).ConfigureAwait(false);
            if (count == 0) throw new EndOfStreamException();
            offset += count;
        }
    }
    private static async Task Send(NetworkStream stream, ushort type, string json, CancellationToken token)
    {
        var bytes = Encoding.UTF8.GetBytes(json); var header = new byte[16];
        Encoding.ASCII.GetBytes("A2SS").CopyTo(header, 0);
        BinaryPrimitives.WriteUInt16LittleEndian(header.AsSpan(4), type);
        BinaryPrimitives.WriteInt32LittleEndian(header.AsSpan(8), bytes.Length);
        using var write = CancellationTokenSource.CreateLinkedTokenSource(token);
        write.CancelAfter(2000);
        await stream.WriteAsync(header, write.Token).AsTask().WaitAsync(write.Token).ConfigureAwait(false);
        await stream.WriteAsync(bytes, write.Token).AsTask().WaitAsync(write.Token).ConfigureAwait(false);
    }
}
