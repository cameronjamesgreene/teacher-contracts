from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from contract_search import build_passages, index_document, open_database, read_passages, search_passages
from utils import Document


def document(document_id: str, text: str) -> Document:
    return Document(
        district="Test District",
        file_name=f"{document_id}.pdf",
        path=Path(f"/{document_id}.pdf"),
        document_id=document_id,
        text_path=Path(f"/{document_id}.txt"),
        text=text,
        lower_text=text.lower(),
        pages=text.split("\f"),
        lower_pages=[page.lower() for page in text.split("\f")],
        page_count=len(text.split("\f")),
        text_status="usable",
    )


class ContractSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "contracts.sqlite3"
        self.connection = open_database(self.db)

    def tearDown(self) -> None:
        self.connection.close()
        self.tempdir.cleanup()

    def test_passages_preserve_pdf_pages_and_heading(self) -> None:
        passages = build_passages(
            "ARTICLE VI INSURANCE\n\nThe Board shall pay health insurance premiums.\f"
            "ARTICLE VII LEAVE\n\nTeachers receive ten sick leave days."
        )
        self.assertEqual([(start, end) for start, end, _, _ in passages], [(1, 1), (2, 2)])
        self.assertIn("INSURANCE", passages[0][2])
        self.assertIn("health insurance", passages[0][3])
        self.assertIn("LEAVE", passages[1][2])
        self.assertIn("sick leave", passages[1][3])

    def test_article_boundaries_win_over_size_packing(self) -> None:
        passages = build_passages(
            "ARTICLE I RECOGNITION\n\nThe Board recognizes the Association.\n\n"
            "ARTICLE II SALARIES\n\nThe Board shall pay salaries."
        )
        self.assertEqual(len(passages), 2)
        self.assertIn("RECOGNITION", passages[0][2])
        self.assertNotIn("salaries", passages[0][3].lower())
        self.assertIn("SALARIES", passages[1][2])

    def test_search_is_scoped_to_document(self) -> None:
        index_document(self.connection, document("one", "ARTICLE PAY\n\nTeachers receive an annual salary increment."))
        index_document(self.connection, document("two", "ARTICLE PAY\n\nTeachers receive an annual salary increment."))
        hits = search_passages(self.connection, "one", "annual salary increment")
        self.assertTrue(hits)
        self.assertEqual({hit.document_id for hit in hits}, {"one"})
        self.assertEqual(read_passages(self.connection, "one", [hits[0].passage_id])[0].document_id, "one")
        self.assertEqual(read_passages(self.connection, "two", [hits[0].passage_id]), [])

    def test_reindex_replaces_old_text_and_is_idempotent(self) -> None:
        first = document("one", "ARTICLE PAY\n\nThe Board shall pay a stipend.")
        self.assertEqual(index_document(self.connection, first), 1)
        self.assertEqual(index_document(self.connection, first), 1)
        replacement = document("one", "ARTICLE PAY\n\nThe Board shall pay an overtime premium.")
        self.assertEqual(index_document(self.connection, replacement), 1)
        self.assertFalse(search_passages(self.connection, "one", "stipend"))
        self.assertTrue(search_passages(self.connection, "one", "overtime premium"))

    def test_invalid_or_empty_query_fails_clearly(self) -> None:
        index_document(self.connection, document("one", "Teachers receive leave."))
        with self.assertRaises(ValueError):
            search_passages(self.connection, "one", "a the is")
        with self.assertRaises(ValueError):
            search_passages(self.connection, "one", "leave", limit=31)


if __name__ == "__main__":
    unittest.main()
