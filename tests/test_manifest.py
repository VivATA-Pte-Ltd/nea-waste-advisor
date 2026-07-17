import copy
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_standards", ROOT / "scripts" / "update_standards.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StandardsManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "standards.json").read_text(encoding="utf-8"))

    def test_manifest_validates(self):
        module.validate(self.data)

    def test_official_2025_rates(self):
        expected = {
            "Office / Classroom": 15,
            "Hotel / Dormitory / Store / Industrial": 10,
            "Retail Shop / Trade Premises": 30,
            "Supermarket / Market / Department Store": 100,
            "Restaurant / Eating House / Food Centre / Canteen / Pantry / Food Shop / Food Processing Establishment": 200,
            "Residential Premises": 20,
            "Petrol Station": 300,
        }
        self.assertEqual({key: item["rate"] for key, item in self.data["rates"].items()}, expected)

    def test_key_thresholds(self):
        rules = self.data["rules"]
        self.assertEqual(rules["binCentreAboveLitresPerDay"], 1000)
        self.assertEqual(rules["enclosedSystemAtOrAboveLitresPerDay"], 4000)
        self.assertEqual(rules["storageDays"], 2)
        self.assertEqual(rules["wheeledBinCapacityLitres"], 660)
        self.assertEqual(rules["pwcsResidentialUnits"], 500)

    def test_rejects_conflicting_thresholds(self):
        altered = copy.deepcopy(self.data)
        altered["rules"]["binCentreAboveLitresPerDay"] = 5000
        with self.assertRaises(RuntimeError):
            module.validate(altered)

    def test_checksum_shape(self):
        digest = self.data["code"]["pdfSha256"]
        self.assertEqual(len(digest), 64)
        int(digest, 16)


if __name__ == "__main__":
    unittest.main()
