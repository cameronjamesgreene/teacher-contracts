from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evaluate_question_extraction import (
    apply_review_responses,
    make_blinded_packet,
    score_packet,
    select_documents,
    write_review_tasks,
)


class QuestionEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_csv(self, name: str, rows: list[dict]) -> Path:
        path = self.root / name
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_stratified_selection_is_reproducible_and_excludes_unusable(self) -> None:
        manifest = self.write_csv("manifest.csv", [
            {"document_id": "short", "text_status": "usable", "pdf_pages": "4"},
            {"document_id": "medium", "text_status": "usable", "pdf_pages": "50"},
            {"document_id": "long", "text_status": "usable", "pdf_pages": "200"},
            {"document_id": "bad", "text_status": "ocr_needed", "pdf_pages": "50"},
        ])
        first = select_documents(manifest, 3, 7)
        second = select_documents(manifest, 3, 7)
        self.assertEqual(first, second)
        self.assertEqual({row["document_id"] for row in first}, {"short", "medium", "long"})

    def test_source_grounded_task_and_response_collection(self) -> None:
        source = self.root / "source.txt"
        source.write_text("Page one\fSalary schedule appears here.\fPage three", encoding="utf-8")
        manifest = self.write_csv("manifest.csv", [{
            "document_id": "doc", "district": "District", "file_name": "x.pdf", "source_path": "/tmp/x.pdf",
            "text_path": str(source), "text_status": "usable", "pdf_pages": "3",
        }])
        packet = self.write_csv("packet.csv", [{
            "review_id": "review", "document_id": "doc", "district": "District", "file_name": "x.pdf",
            "question_id": "pay_salary_schedule_001", "question": "Salary schedule?",
            "a_answer": "yes", "a_evidence": "Salary schedule", "a_page": "2", "a_confidence": "high", "a_coder_notes": "",
            "b_answer": "not_discussed", "b_evidence": "", "b_page": "not_applicable", "b_confidence": "low", "b_coder_notes": "",
            **{f"{label}_{field}_correct": "" for label in ("a", "b") for field in ("status", "value", "evidence", "page", "overall")},
            "reviewer_notes": "",
        }])
        task_dir = self.root / "tasks"
        self.assertEqual(write_review_tasks(packet, manifest, self.root / "index.sqlite3", task_dir), 1)
        task = (task_dir / "review.task.md").read_text()
        self.assertIn("Salary schedule appears here.", task)
        self.assertIn("contract_search.py", task)
        (task_dir / "review.response.json").write_text(json.dumps({
            "review_id": "review",
            "a": {field: "yes" for field in ("status", "value", "evidence", "page", "overall")},
            "b": {field: "no" for field in ("status", "value", "evidence", "page", "overall")},
            "reviewer_notes": "A is supported on page 2.",
        }), encoding="utf-8")
        completed = self.root / "completed.csv"
        self.assertEqual(apply_review_responses(packet, task_dir, completed), 1)
        with completed.open(encoding="utf-8") as result:
            row = next(csv.DictReader(result))
        self.assertEqual(row["a_overall_correct"], "yes")
        self.assertEqual(row["b_overall_correct"], "no")

    def test_blinding_and_scoring_do_not_depend_on_a_system_position(self) -> None:
        template = self.write_csv("template.csv", [{
            "document_id": "doc", "district": "District", "file_name": "x.pdf", "text_status": "usable",
            "question_id": "pay_salary_schedule_001", "question": "Salary schedule?", "answer_type": "yes/no",
            "keywords": "salary", "expected_answer": "", "expected_evidence": "", "expected_page": "", "adjudicator_notes": "",
        }])
        baseline = self.write_csv("baseline.csv", [{
            "document_id": "doc", "Question ID": "pay_salary_schedule_001", "answer": "yes",
            "evidence": "salary schedule", "page number": "2", "confidence": "high", "coder notes": "",
        }])
        candidate = self.root / "candidate.jsonl"
        candidate.write_text(json.dumps({"document_id": "doc", "answers": [{
            "question_id": "pay_salary_schedule_001", "answer": "no", "evidence": "", "page": "not_applicable",
            "confidence": "low", "coder_notes": "",
        }]}) + "\n", encoding="utf-8")
        packet = self.root / "packet.csv"
        key = self.root / "key.csv"
        make_blinded_packet(template, baseline, candidate, packet, key, seed=3)
        with packet.open(encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 1)
        with key.open(encoding="utf-8") as source:
            mapping = list(csv.DictReader(source))[0]["a_system"]
        if mapping == "baseline":
            rows[0]["a_overall_correct"] = "yes"
            rows[0]["b_overall_correct"] = "no"
        else:
            rows[0]["a_overall_correct"] = "no"
            rows[0]["b_overall_correct"] = "yes"
        with packet.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        report = self.root / "report.json"
        score_packet(packet, key, report)
        result = json.loads(report.read_text())
        self.assertEqual(result["metrics"]["overall"]["baseline"]["accuracy"], 1.0)
        self.assertEqual(result["metrics"]["overall"]["candidate"]["accuracy"], 0.0)


if __name__ == "__main__":
    unittest.main()
