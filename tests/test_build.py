"""Tests for scripts/build.py: the example builds, inheritance works, mistakes are reported.

They read YAML only (no LaTeX, no internet): python -m unittest discover -s tests -v
"""
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import build  # noqa: E402


def write(root, files):
    """Writes {relative path: text} under root (an empty text makes an empty file)."""
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


# a small valid data folder: one base ("b") with one technical experience ("t")
BASE = {
    "person.yaml": """
        name: Ana Silva
        email: ana@example.com
        phone: "+55 11 90000-0000"
        location: {pt: Brasil, en: Brazil}
        linkedin: https://www.linkedin.com/in/ana-example/
        github: https://github.com/ana-example
        """,
    "technical/t.yaml": """
        institution: Example University
        start: 2021-03
        end: 2022-01
        mode: on-site
        """,
    "bases/b/header.yaml": """
        titles:
          pt: Analista de Dados, SQL, Python
          en: Data Analyst, SQL, Python
        """,
    "bases/b/summary.yaml": """
        pt: Resumo.
        en: Summary.
        """,
    "bases/b/skills.yaml": """
        langs:
          name: Linguagens, Languages
          skills: Python, SQL
        tools:
          name: Ferramentas, Tools
          skills: Git, Docker
        """,
    "bases/b/technical/title.yaml": """
        pt: Experiência Técnica
        en: Technical Experience
        """,
    "bases/b/technical/01-t.yaml": """
        title: {pt: Pesquisa, en: Research}
        bullets:
          pt: [Fiz A., Fiz B.]
          en: [Did A., Did B.]
        """,
}


class DataTest(unittest.TestCase):
    """Each test gets its own data folder; build.py reads it as its data."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.data = self.root / "data"
        self.old = build.ROOT, build.DATA
        build.ROOT, build.DATA = self.root, self.data
        write(self.data, BASE)

    def tearDown(self):
        build.ROOT, build.DATA = self.old
        shutil.rmtree(self.root)

    def job(self, files, base="b"):
        """A job CV "j" built on a base, with the given files (paths inside jobs/j/)."""
        write(self.data, {"jobs/j/" + base: "", **{"jobs/j/" + k: v for k, v in files.items()}})
        return build.cv("j")

    def fails(self, message, name="b"):
        with self.assertRaises(build.CVError) as error:
            build.cv(name)
        self.assertIn(message, str(error.exception))


@unittest.skipUnless((REPO / "example").is_dir(), "no example/ (a private copy with only data/)")
class TestExample(unittest.TestCase):
    """The example in example/ is the documentation: every CV must build."""

    def setUp(self):
        self.old = build.ROOT, build.DATA
        build.ROOT, build.DATA = REPO, REPO / "example"

    def tearDown(self):
        build.ROOT, build.DATA = self.old

    def test_every_cv_builds_in_every_language(self):
        p = build.person()
        for name in build.cv_names():
            c = build.cv(name)
            for lang in build.LANGS:
                tex = build.content(p, c, lang)
                self.assertIn(r"\def\HeaderName{Alex Morgan}", tex, f"{name}-{lang}")

    def test_job_skills_change_the_base_line_by_line(self):
        lines = build.cv("acme")["sections"]["skills"]
        self.assertEqual(list(lines), ["langs", "analysis", "experiments"])  # tools removed, one added

    def test_job_folder_keeps_only_its_items(self):
        items = build.cv("globex")["sections"]["professional"]["items"]
        self.assertEqual([i["org"] for i in items], ["Vela Retail"])
        base = build.cv("engineering")["sections"]["professional"]["items"][0]
        self.assertEqual(items[0]["title"]["en"], "Data Engineer (Platform)")  # changed
        self.assertEqual(items[0]["bullets"], base["bullets"])                 # inherited


class TestInheritance(DataTest):

    def test_job_without_a_folder_uses_the_base(self):
        self.assertEqual(self.job({})["source"]["technical"], "b")

    def test_empty_file_shows_the_item_as_the_base(self):
        c = self.job({"technical/01-t.yaml": ""})
        self.assertEqual(c["sections"]["technical"]["items"][0]["title"]["pt"], "Pesquisa")
        self.assertEqual(c["sections"]["technical"]["title"]["pt"], "Experiência Técnica")

    def test_file_with_some_fields_changes_only_those(self):
        c = self.job({"technical/01-t.yaml": "title: {pt: Outra, en: Other}\n"})
        item = c["sections"]["technical"]["items"][0]
        self.assertEqual(item["title"]["en"], "Other")
        self.assertEqual(item["bullets"]["en"], ["Did A.", "Did B."])

    def test_empty_file_for_an_item_the_base_does_not_show(self):
        write(self.data, {"technical/x.yaml": (self.data / "technical/t.yaml").read_text()})
        with self.assertRaisesRegex(build.CVError, "the base does not show 'x'"):
            self.job({"technical/01-x.yaml": ""})

    def test_skills_replace_remove_add(self):
        c = self.job({"skills.yaml": """
            langs:
              skills: Python, SQL, R
            tools:
            cloud:
              name: Nuvem, Cloud
              skills: AWS
            """})
        lines = c["sections"]["skills"]
        self.assertEqual(list(lines), ["langs", "cloud"])
        self.assertEqual(lines["langs"]["name"]["pt"], "Linguagens")   # kept from the base
        self.assertEqual(lines["langs"]["skills"]["en"], "Python, SQL, R")


class TestMistakes(DataTest):

    def test_experience_folder_needs_a_title(self):
        (self.data / "bases/b/technical/title.yaml").unlink()
        self.fails("title.yaml is missing")

    def test_education_has_a_fixed_title(self):
        write(self.data, {"bases/b/education/title.yaml": "pt: A\nen: B\n"})
        self.fails("education/ has no title.yaml")

    def test_too_many_bullets(self):
        write(self.data, {"bases/b/technical/01-t.yaml": """
            title: {pt: P, en: R}
            bullets:
              pt: [a, b, c, d, e]
              en: [a, b, c, d, e]
            """})
        self.fails("at most 4")

    def test_month_must_be_valid(self):
        write(self.data, {"technical/t.yaml": "institution: U\nstart: 2021-13\nend: present\nmode: remote\n"})
        self.fails("must be a month like 2022-08")

    def test_skill_name_needs_two_languages(self):
        write(self.data, {"bases/b/skills.yaml": "langs:\n  name: A, B, C\n  skills: Python\n"})
        self.fails("found 3")

    def test_job_cannot_remove_a_skill_line_the_base_lacks(self):
        with self.assertRaisesRegex(build.CVError, "the base has no such line"):
            self.job({"skills.yaml": "nope:\n"})

    def test_unknown_folder_is_reported(self):
        (self.data / "bases/b/tecnical").mkdir()
        self.fails("unknown folder")


class TestLatex(unittest.TestCase):

    def test_special_characters_are_escaped(self):
        self.assertEqual(build.esc("R&D 50% #1"), r"R\&D 50\% \#1")

    def test_links_become_href(self):
        self.assertEqual(build.rich("on [NASA ADS](https://ui.adsabs.harvard.edu/abs/x) & more"),
                         r"on \href{https://ui.adsabs.harvard.edu/abs/x}{NASA ADS} \& more")


if __name__ == "__main__":
    unittest.main()
