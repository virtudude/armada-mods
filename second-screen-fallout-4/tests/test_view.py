"""Run real DOM/action tests with an optional installed Chromium browser."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BROWSER = shutil.which('chromium') or shutil.which('chromium-browser')


@unittest.skipUnless(BROWSER, 'Chromium is not installed')
class ViewTests(unittest.TestCase):
    def test_touch_actions_and_state(self):
        with tempfile.TemporaryDirectory(prefix='pipboy-view-test-') as tmp:
            folder = Path(tmp)
            shutil.copytree(ROOT / 'view', folder / 'view')
            html = (folder / 'view/index.html').read_text()
            fixture = {
                'connected': True,
                'data': {
                    'PlayerInfo': {'PlayerName': '<img src=x onerror=alert(1)>', 'XPLevel': 2},
                    'Status': {},
                    'Inventory': {'Version': 4, '43': [
                        {'_id': 90, 'text': 'Test rifle', 'filterFlag': 2, 'count': 1},
                        {'_id': 91, 'text': 'Test aid', 'filterFlag': 8, 'count': 3},
                    ]},
                    'Radio': [{'_id': 10, 'text': 'Test station', 'inRange': False}],
                    'Map': {'CurrWorldspace': 'Commonwealth', 'World': {
                        'Extents': {'NWX': 0, 'NWY': 100, 'NEX': 100, 'NEY': 100, 'SWX': 0, 'SWY': 0},
                        'Player': {'_id': 15, 'X': 50, 'Y': 50},
                    }},
                },
            }
            setup = '<script>window.commands=[]; window.armada={data:"",last:' + json.dumps(fixture) + ',send(c){commands.push(c)}};</script>'
            checks = '''<script>
window.addEventListener('load', async () => {
 const result=document.createElement('pre');result.id='test-result';document.body.append(result);
 const assert=(ok,msg)=>{if(!ok)throw Error(msg)};
 try {
  assert(!document.querySelector('.player-name img'),'Game text interpreted as HTML');
  assert(document.querySelector('.player-name').textContent.includes('<img'),'Player name not preserved');
  assert(!$('connection').textContent&&!$('display').textContent.includes('CONNECTED'),'Normal status must not show debug labels');
  assert(document.querySelector('.limb-health'),'Native HP condition meter missing');
  assert(document.querySelector('.vital-level .meter'),'Native XP strip missing');
  switchPage('INV');document.querySelector('[data-game-action]').click();
  assert(commands[0].action==='use'&&commands[0].id===90&&commands[0].version===4,'Wrong equip command');
  const disabled=JSON.parse(JSON.stringify(armada.last));disabled.data.Status.IsPlayerInDialogue=true;armada.onState(disabled);
  assert(document.querySelector('[data-game-action]').disabled,'Dialogue must gate actions');
  disabled.data.Status={};armada.onState(disabled);switchPage('RADIO');
  assert(document.querySelector('[data-game-action]').disabled,'Out of range station must stay disabled');
  armada.onState(disabled);assert(document.querySelector('[data-game-action]').disabled,'Update enabled unavailable radio');
  switchPage('MAP');const p=worldToUV(50,50);assert(p.u===.5&&p.v===.5,'Map coordinate transform');
  category='Local';render();assert(document.querySelector('.map-tools').textContent.includes('Refresh'),'Local map refresh missing');
  disabled.confirm={token:'test-token',label:'Use Test aid?',expires:Date.now()/1000+5};armada.onState(disabled);
  assert(!$('confirmation').hidden&&$('confirm').disabled,'Confirmation must prevent double tap');
  await new Promise(r=>setTimeout(r,400));$('confirm').click();
  assert(commands.at(-1).action==='confirm'&&commands.at(-1).token==='test-token','Confirmation not sent');
  armada.onState(disabled);assert($('confirmation').hidden,'Confirmed prompt reopened');
  armada.onState({connected:false,data:{Perks:[]},message:'Waiting for game'});
  assert($('content').textContent.includes('Waiting for game'),'Missing honest disconnected empty state');
  result.textContent='PASS';
 } catch(e) {result.textContent='FAIL: '+e.stack;}
});
</script>'''
            (folder / 'view/index.html').write_text(html.replace('<script defer', setup + '<script defer', 1).replace('</body>', checks + '</body>'))
            run = subprocess.run([
                BROWSER, '--headless', '--no-sandbox', '--disable-gpu',
                '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
                '--allow-file-access-from-files', '--user-data-dir=' + str(folder / 'profile'),
                '--virtual-time-budget=2000', '--dump-dom', (folder / 'view/index.html').as_uri(),
            ], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr[-2000:])
            self.assertIn('<pre id="test-result">PASS</pre>', run.stdout, run.stdout[-5000:])

    @unittest.skipUnless(os.environ.get('PIPBOY_TEST_ASSETS'), 'Set PIPBOY_TEST_ASSETS to an extracted game cache')
    def test_native_font_and_animation(self):
        data_dir = Path(os.environ['PIPBOY_TEST_ASSETS']).resolve()
        assets = json.loads((data_dir / 'assets/manifest.json').read_text())
        with tempfile.TemporaryDirectory(prefix='pipboy-native-test-') as tmp:
            folder = Path(tmp)
            shutil.copytree(ROOT / 'view', folder / 'view')
            fixture = {'connected': True, 'assets': assets, 'data': {
                'PlayerInfo': {'PlayerName': 'Native asset test', 'CurrHP': 60, 'MaxHP': 100, 'XPLevel': 1},
                'Status': {}, 'Stats': {'BodyFlags': 0, 'HeadFlags': 0},
            }}
            setup = '<script>window.armada={data:' + json.dumps(data_dir.as_uri()) + ',last:' + json.dumps(fixture) + ',send(){}};</script>'
            checks = """<script>
window.addEventListener('load', () => {
 const result=document.createElement('pre');result.id='native-test-result';document.body.append(result);
 setTimeout(async () => {
  await document.fonts.ready;
  const loaded=[...document.fonts].filter(f=>f.family==='PipBoy'&&f.status==='loaded');
  if(loaded.length!==2 || !document.fonts.check('28px PipBoy') || !document.fonts.check('700 28px PipBoy')) {
   result.textContent='FAIL: Native font not loaded'; return;
  }
  const canvas=document.querySelector('canvas[data-animation="status"]');
  const before=canvas?.dataset.frame;
  const seen=new Set([before]);
  // Chromium's virtual-time runner pauses compositor callbacks. Advance the
  // production frame renderer on that same clock while images load normally.
  const interval=setInterval(()=>{renderAnimations(performance.now());seen.add(canvas?.dataset.frame)},40);
  setTimeout(()=>{
   clearInterval(interval);
   result.textContent=[...seen].filter(Boolean).length>1?'PASS':'FAIL: Native body frame did not advance';
  },1250);
 },700);
});
</script>"""
            html = (folder / 'view/index.html').read_text()
            (folder / 'view/index.html').write_text(html.replace('<script defer', setup + '<script defer', 1).replace('</body>', checks + '</body>'))
            run = subprocess.run([
                BROWSER, '--headless', '--no-sandbox', '--disable-gpu',
                '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
                '--allow-file-access-from-files', '--user-data-dir=' + str(folder / 'profile'),
                '--virtual-time-budget=4000', '--dump-dom', (folder / 'view/index.html').as_uri(),
            ], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr[-2000:])
            self.assertTrue('<pre id="native-test-result">PASS</pre>' in run.stdout, run.stdout[-2000:])


    @unittest.skipUnless(os.environ.get('PIPBOY_TEST_ASSETS'), 'Set PIPBOY_TEST_ASSETS to an extracted game cache')
    def test_crt_sweep_lights_artwork_and_leaves_empty_space_dark(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow is needed to inspect Chromium screenshot pixels')
        data_dir = Path(os.environ['PIPBOY_TEST_ASSETS']).resolve()
        assets = json.loads((data_dir / 'assets/manifest.json').read_text())
        # Exercise the same trusted runtime descriptor used by the WebKit host.
        for name in ('scan', 'verticalScan'):
            descriptor = assets['effects'][name]
            descriptor['dataURI'] = 'data:image/png;base64,' + base64.b64encode(
                (data_dir / descriptor['path']).read_bytes()).decode('ascii')
        fixture = {'assets': assets, 'data': {'Status': {'EffectColor': [.08, 1, .09]}}}
        with tempfile.TemporaryDirectory(prefix='pipboy-crt-test-') as tmp:
            folder = Path(tmp)
            shutil.copy(ROOT / 'view/crt.js', folder / 'crt.js')
            images = []
            # A static source at half brightness leaves room for the recovered
            # scan highlight. No layout, game animation, or screenshot capture
            # feeds the production filter itself.
            for name, phase in [('rest', 1.5), ('sweep', .5 - 13 / 32 / 3)]:
                html = '<html><body style="margin:0;background:black">'
                html += '<div id="display" style="position:absolute;width:640px;height:480px">'
                html += '<div style="position:absolute;left:100px;top:100px;width:100px;height:200px;background:rgb(10,128,12)"></div></div>'
                html += '<script>window.armada={data:' + json.dumps(data_dir.as_uri()) + '};</script>'
                html += '<script src="crt.js"></script><script>PipboyCRT.update(' + json.dumps(fixture) + ');PipboyCRT.freeze(' + str(phase) + ');</script></body></html>'
                page = folder / (name + '.html')
                page.write_text(html)
                screenshot = folder / (name + '.png')
                run = subprocess.run([
                    BROWSER, '--headless', '--no-sandbox', '--disable-gpu',
                    '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
                    '--allow-file-access-from-files', '--user-data-dir=' + str(folder / 'profile'),
                    '--window-size=640,600', '--virtual-time-budget=1000',
                    '--screenshot=' + str(screenshot), page.as_uri(),
                ], text=True, capture_output=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stderr[-2000:])
                images.append(Image.open(screenshot).convert('RGB'))
            def mean_green(image, box):
                histogram = image.crop(box).getchannel('G').histogram()
                return sum(value * count for value, count in enumerate(histogram)) / sum(histogram)
            rest, sweep = images
            self.assertGreater(mean_green(sweep, (130, 220, 150, 260)),
                               mean_green(rest, (130, 220, 150, 260)) + 8,
                               'Native scan did not brighten existing UI pixels')
            for image in images:
                self.assertEqual(mean_green(image, (300, 220, 320, 260)), 0,
                                 'Scan painted a band into empty screen space')
                self.assertGreater(mean_green(image, (207, 200, 210, 250)), 0,
                                   'Original UI did not bloom beyond two pixels')
            self.assertAlmostEqual(mean_green(rest, (207, 200, 210, 250)),
                                   mean_green(sweep, (207, 200, 210, 250)), delta=.5,
                                   msg='Bloom must sample the original UI, not the swept highlight')


if __name__ == '__main__':
    unittest.main()
