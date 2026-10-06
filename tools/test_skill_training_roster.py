"""Offline skill-training preservation from Skland normalization to roster."""
import unittest
from ak_tactic.skland import normalize_opers
from ak_tactic.skland_roster import build_roster


class EmptyEquipmentCalculator:
    def _load_uniequip(self):
        return {}

    def _load_battle_equip(self):
        return {}


class SkillTrainingRosterTests(unittest.TestCase):
    def make_roster(self, ordinary, mastery):
        char = {"charId": "char_4063_quartz", "evolvePhase": 2, "level": 1,
                "potentialRank": 0, "favorPercent": 0,
                "skills": [{"id": "skcom_atk_up[2]", "specializeLevel": mastery}]}
        if ordinary is not None:
            char["mainSkillLvl"] = ordinary
        return build_roster(raw={"uid": "offline", "charInfo": {char["charId"]: {"name": "石英"}},
                                 "opers": normalize_opers([char])},
                            calc=EmptyEquipmentCalculator())["opers"][0]

    def test_actual_ordinary_levels_preserved(self):
        for level in range(1, 8):
            with self.subTest(level=level):
                row = self.make_roster(level, 0)
                self.assertEqual(row["mainSkillLvl"], level)
                self.assertEqual(row["mastery"]["skcom_atk_up[2]"], 0)

    def test_each_mastery_preserved(self):
        for mastery in range(4):
            with self.subTest(mastery=mastery):
                row = self.make_roster(7, mastery)
                self.assertEqual(row["mastery"], {"skcom_atk_up[2]": mastery})

    def test_missing_level_stays_missing_not_invented(self):
        self.assertIsNone(self.make_roster(None, 0)["mainSkillLvl"])

    def test_invalid_level_not_truncated_by_producer(self):
        self.assertEqual(self.make_roster(3.5, 0)["mainSkillLvl"], 3.5)
        self.assertEqual(self.make_roster(7, 4)["mastery"]["skcom_atk_up[2]"], 4)


if __name__ == "__main__":
    unittest.main()
