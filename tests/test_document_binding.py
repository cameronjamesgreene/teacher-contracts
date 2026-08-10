"""Every retrieval/grounding entry point must be told which document it refers to.

These functions used to default to Manchester, the development document. A caller
that forgot the argument therefore searched one district's quote against another
district's pages and got a page number back — confident, plausible and wrong, with
nothing in the output to say so. `grind_reconcile` additionally stamped Manchester's
document_id onto whatever it reconciled.

The defaults are gone. These tests fail if anyone reintroduces one, which is the
point: the failure mode is silent, so the guard cannot be.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import grind_retrieve
from grind_retrieve import DocumentContext


class DocumentIsRequiredTest(unittest.TestCase):
    """No document-taking function may supply its own document."""

    # name -> the parameter that carries the document (or the pages taken from one)
    ENTRY_POINTS = {
        "fused_passages": "doc",
        "ground": "doc",
        "exact_page": "doc",
        "document_pages": "doc",
        "locate_in_document": "pages",
    }

    def test_no_entry_point_defaults_its_document(self) -> None:
        for name, parameter in self.ENTRY_POINTS.items():
            with self.subTest(function=name):
                signature = inspect.signature(getattr(grind_retrieve, name))
                self.assertIn(parameter, signature.parameters,
                              f"{name} no longer takes {parameter}")
                self.assertIs(
                    signature.parameters[parameter].default, inspect.Parameter.empty,
                    f"{name}({parameter}=...) has a default again; a caller that omits "
                    f"it will silently ground against the wrong document")

    def test_omitting_the_document_raises(self) -> None:
        with self.assertRaises(TypeError):
            grind_retrieve.ground("a quote long enough to check", [])  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            grind_retrieve.document_pages()                            # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            grind_retrieve.locate_in_document("a quote long enough")   # type: ignore[call-arg]

    def test_supplying_the_document_still_works(self) -> None:
        doc = DocumentContext(document_id="d", text_path=Path("/nonexistent.txt"))
        grounding = grind_retrieve.ground("a quote long enough to check", [], doc=doc)
        self.assertFalse(grounding.verbatim)


class NoModuleLevelManchesterTest(unittest.TestCase):
    """The default document is a CLI argument default, not a module-level object.

    A module-level `MANCHESTER = DocumentContext(...)` is what made the defaults easy
    to write in the first place, so it stays gone; `DEFAULT_DOCUMENT_ID` is a string
    and cannot be passed where a document is expected.
    """

    def test_default_is_an_id_not_a_context(self) -> None:
        self.assertFalse(hasattr(grind_retrieve, "MANCHESTER"))
        self.assertIsInstance(grind_retrieve.DEFAULT_DOCUMENT_ID, str)

    def test_document_binding_globals_start_unset(self) -> None:
        """The per-run DOC globals are None until a CLI binds them."""
        for module_name in ("grind_verify", "grind_sweep", "grind_subset"):
            with self.subTest(module=module_name):
                module = __import__(module_name)
                self.assertIsNone(
                    module.DOC,
                    f"{module_name}.DOC is pre-bound to a document; a run that forgets "
                    f"--document-id would code the wrong contract under the right name")


if __name__ == "__main__":
    unittest.main()
