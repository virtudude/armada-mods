using Microsoft.Xna.Framework;
using StardewValley;
using StardewValley.Characters;
using StardewValley.Menus;

namespace ArmadaStardew;

// Read-only equivalents of SkillsPage and AnimalPage. In particular, never
// construct the menus themselves: IClickableMenu construction halts the farmer.
internal static class CharacterPages
{
    public static object Skin(Assets art) => new
    {
        skillEmpty = art.Get(Game1.mouseCursors, new Rectangle(129, 338, 8, 9)),
        skillFull = art.Get(Game1.mouseCursors, new Rectangle(137, 338, 8, 9)),
        milestoneEmpty = art.Get(Game1.mouseCursors, new Rectangle(145, 338, 14, 9)),
        milestoneFull = art.Get(Game1.mouseCursors, new Rectangle(159, 338, 14, 9)),
        pet = art.Get(Game1.mouseCursors, new Rectangle(32, 0, 10, 10)),
        petStates = Enumerable.Range(0, 3).Select(i => art.Get(Game1.mouseCursors_1_6, new Rectangle(273 + 9 * i, 253, 9, 9))).ToArray(),
        animalCracker = art.Get(Game1.objectSpriteSheet_2, new Rectangle(16, 242, 15, 11)),
        carrot = art.Get(Game1.objectSpriteSheet_2, new Rectangle(0, 160, 16, 16)),
        halfHeart = art.Get(Game1.mouseCursors, new Rectangle(211, 428, 4, 6)),
        skillsTab = art.Get(Game1.mouseCursors, new Rectangle(16, 368, 16, 16)),
        animalsTab = art.Get(Game1.mouseCursors_1_6, new Rectangle(257, 246, 16, 16)),
        mastery = art.Get(Game1.mouseCursors_1_6, new Rectangle(457, 298, 11, 11)),
        // SkillsPage deliberately shows the silhouette until the first find.
        stardrop = art.Get(Game1.mouseCursors_1_6, new Rectangle(421, 314, 12, 14)),
        stardropFound = art.Get(Game1.mouseCursors_1_6, new Rectangle(399, 314, 12, 14))
    };

    public static object Skills(Assets art)
    {
        var p = Game1.player;
        // Display order differs from Farmer's numeric skill IDs.
        var rows = new[] { (id: 0, x: 10), (id: 3, x: 30), (id: 2, x: 60), (id: 1, x: 20), (id: 4, x: 120) };
        return new
        {
            name = p.Name, title = p.getTitle(), level = p.Level,
            health = p.health, maxHealth = p.maxHealth, stamina = p.Stamina, maxStamina = p.MaxStamina,
            stardrops = Utility.numStardropsFound(p),
            mastery = new { experience = Game1.stats.Get("MasteryExp"), level = MasteryTrackerMenu.getCurrentMasteryLevel() },
            rows = rows.Select(row =>
            {
                int level = p.GetSkillLevel(row.id);
                int baseLevel = p.GetUnmodifiedSkillLevel(row.id);
                return new
                {
                    id = row.id, name = Farmer.getSkillDisplayNameFromIndex(row.id), level, baseLevel,
                    boosted = level > baseLevel, description = SkillDescription(row.id, level),
                    image = art.Get(Game1.mouseCursors, new Rectangle(row.x, 428, 10, 10)),
                    professions = new[] { 5, 10 }.Select(tier => (tier, id: p.getProfessionForSkill(row.id, tier)))
                        .Where(prof => prof.id >= 0 && baseLevel >= prof.tier && p.professions.Contains(prof.id))
                        .Select(prof =>
                        {
                            var lines = LevelUpMenu.getProfessionDescription(prof.id);
                            return new { id = prof.id, level = prof.tier, name = lines.FirstOrDefault() ?? "",
                                description = string.Join("\n", lines.Skip(1)),
                                image = art.Get(Game1.mouseCursors, new Rectangle(prof.id % 6 * 16, 624 + prof.id / 6 * 16, 16, 16)) };
                        }).ToArray()
                };
            }).ToArray()
        };
    }

    private static string SkillDescription(int skill, int level)
    {
        if (level <= 0) return "";
        string Load(int key, int value) => Game1.content.LoadString("Strings\\StringsFromCSFiles:SkillsPage.cs." + key, value);
        return skill switch
        {
            0 => Load(11592, level) + "\n" + Load(11594, level),
            1 => Load(11598, level),
            2 => Load(11596, level),
            3 => Load(11600, level),
            4 => Load(11602, level * 5),
            _ => ""
        };
    }

    public static object Animals(Assets art)
    {
        var animals = new List<Character>();
        // Same search boundary as AnimalPage.GetAllAnimals, including interiors.
        Utility.ForEachLocation(location =>
        {
            animals.AddRange(location.characters.Where(c => (c is Pet or Horse) && !c.hideFromAnimalSocialMenu.Value));
            animals.AddRange(location.animals.Values.Where(a => !a.hideFromAnimalSocialMenu.Value));
            return true;
        }, true, false);
        animals.AddRange(Game1.getAllFarmers().Where(p => p.mount != null).Select(p => p.mount));

        // AnimalEntry is a pure data record, not an IClickableMenu. Reusing it
        // preserves the game's exact crop, pet status, and cracker metadata.
        var entries = animals.Distinct().Select(c => new AnimalPage.AnimalEntry(c)).ToArray();
        var ordered = entries.Where(e => e.Animal is Pet)
            .Concat(entries.Where(e => e.Animal is Horse))
            .Concat(entries.Where(e => e.Animal is FarmAnimal)
                .OrderBy(e => e.AnimalBaseType).ThenBy(e => e.AnimalType).ThenByDescending(e => e.FriendshipLevel));
        return ordered.Select(e =>
        {
            var farmAnimal = e.Animal as FarmAnimal;
            int friendship = e.FriendshipLevel;
            // Match AnimalPage's 195-point full-heart threshold and optional
            // half-heart overlay, rather than rounding friendship to 200.
            var hearts = Enumerable.Range(0, 5).Select(i => friendship > (i + 1) * 195 ? 1f
                : friendship >= 0 && friendship % 200 >= 100 && friendship / 200 == i ? .5f : 0f).ToArray();
            return new
            {
                id = e.InternalName, name = e.DisplayName,
                type = farmAnimal?.displayType ?? e.AnimalType,
                kind = e.Animal is Pet ? "pet" : e.Animal is Horse ? "horse" : "animal",
                image = art.Get(e.Texture, e.TextureSourceRect), friendship,
                hearts = hearts.Sum(), heartStates = hearts, maxHearts = 5,
                petState = e.WasPetYet, cracker = e.ReceivedAnimalCracker, carrot = e.special == 1,
                age = farmAnimal?.age.Value, daysOwned = farmAnimal?.daysOwned.Value,
                mood = farmAnimal == null ? "" : AnimalMood(farmAnimal),
                home = farmAnimal?.homeInterior?.DisplayName ?? "",
                location = e.Animal.currentLocation?.DisplayName ?? "",
                happiness = farmAnimal?.happiness.Value, fullness = farmAnimal?.fullness.Value
            };
        }).ToArray();
    }

    private static string AnimalMood(FarmAnimal animal)
    {
        // getMoodMessage writes moodMessage for ordinary moods. Use its exact
        // string selection without touching that net field during snapshots.
        string gender = animal.isMale() ? "Male" : "Female";
        string key = animal.moodMessage.Value switch
        {
            0 => animal.parentId.Value != -1 ? "NewHome_Baby_" + gender
                : "NewHome_Adult_" + gender + "_" + (Game1.dayOfMonth % 2 + 1),
            4 => (Game1.dayOfMonth + animal.myID.Value) % 2 == 0 ? "Hungry1" : "Hungry2",
            5 => "DisturbedByDog_" + gender,
            6 => "LeftOutsideAtNight_" + gender,
            _ => animal.happiness.Value < 30 ? "Sad" : animal.happiness.Value < 200 ? "Fine" : "Happy"
        };
        return Game1.content.LoadString("Strings\\FarmAnimals:MoodMessage_" + key, animal.displayName);
    }
}
