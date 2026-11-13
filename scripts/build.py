#!/usr/bin/env python3
"""Builds the PDFs of a CV, or of all of them: python scripts/build.py <cv|all> [pt|en] [--example]

The data is in data/ (yours) or, if there is no data/, in example/ (--example: always example/):
  person.yaml            who you are (the header facts), the same in every CV
  languages.yaml         optional: the languages you speak, one list per CV language
  technical/<id>.yaml    the facts of each technical experience: institution, start, end, mode
  professional/<id>.yaml the facts of each job: company, start, end, mode
  education/<id>.yaml    the facts of each degree: institution, degree, start and end (years)
  projects/<id>.yaml     the facts of each project: name and link
  bases/<cv>/            a base CV: header.yaml, summary.yaml, skills.yaml, technical/, professional/,
                         projects/ and education/ (each folder: NN-<id>.yaml, what this CV shows
                         of each item, in the NN order; an experience shows a title and bullets, a
                         project or a degree a one-line description; the experience folders also
                         need title.yaml, the section title, while projects and education have a
                         fixed one). Bullets and descriptions can hold links: [text](https://...)
  jobs/<cv>/             a job CV: an empty file named after its base (e.g. "data") and only
                         what it changes; the rest comes from the base. A file (header.yaml,
                         summary.yaml) replaces the base's. Its skills.yaml changes the base's
                         skill lines one by one: the same key replaces that line (only the fields
                         it gives), the key alone removes it, a new key adds a line at the end.
                         A folder (technical/, ...) says which items the job shows, in its NN
                         order: an empty NN-<id>.yaml shows the item as the base does, one with
                         some fields changes only those; title.yaml is optional (else the base's)

Every run writes dist/latex/ (and dist/cvgit-latex.zip): the LaTeX project with ALL
the CVs already in LaTeX. Its config.tex chooses which CV, language and style to compile,
so the same project works in any LaTeX editor. The PDFs are compiled from that same project:
dist/<cv>-<lang>-<style>.pdf (the example goes to dist/example/).
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = "--example" in sys.argv[1:]                       # build the example even if data/ exists
DATA = ROOT / "example" if EXAMPLE or not (ROOT / "data").exists() else ROOT / "data"
LATEX = ROOT / "latex"
DIST = ROOT / "dist" / ("example" if EXAMPLE else "")    # the example never mixes with your PDFs
PROJECT = DIST / "latex"                       # the LaTeX project (every CV), and its zip
LANGS = {"pt": "brazilian", "en": "english"}      # language -> babel option
LABELS = {                                     # section titles, per language
    "pt": {"Summary": "Resumo", "Languages": "Idiomas", "Education": "Formação Acadêmica",
           "Skills": "Competências Técnicas", "Projects": "Projetos Técnicos"},
    "en": {"Summary": "Summary", "Languages": "Languages", "Education": "Education",
           "Skills": "Technical Skills", "Projects": "Technical Projects"},
}
MONTHS = {
    "pt": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
PRESENT = {"pt": "Atual", "en": "Present"}
MODES = {"on-site": {"pt": "Presencial", "en": "On-site"},
         "remote": {"pt": "Remoto", "en": "Remote"},
         "hybrid": {"pt": "Híbrido", "en": "Hybrid"}}
STYLES = sorted(p.name for p in (LATEX / "styles").iterdir() if p.is_dir())
XELATEX = [s for s in STYLES if (LATEX / "styles" / s / "xelatex").exists()]   # styles with system fonts
TITLES = 3
BULLETS = 4                                    # at most, per experience
EXT = ".yaml"
MONTH = re.compile(r"(\d{4})-(\d{2})")
ITEM = re.compile(r"(\d{2})-([a-z0-9][a-z0-9_-]*)\.yaml")


class CVError(Exception):
    """A problem the user can fix: always says which file and what is wrong."""


# ---------------------------------------------------------------- reading the data

def rel(path):
    return path.relative_to(ROOT)


def read(path):
    if not path.exists():
        raise CVError(f"{rel(path)}: file not found")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        raise CVError(f"{rel(path)}: invalid YAML{where}: {getattr(e, 'problem', None) or e}")


def text(value, where, path):
    """A text in every language: {pt: ..., en: ...}."""
    if not isinstance(value, dict) or any(not isinstance(value.get(l), str) or not value[l].strip()
                                          for l in LANGS):
        raise CVError(f"{rel(path)}: {where} needs a text for each language {list(LANGS)}")
    return {l: " ".join(value[l].split()) for l in LANGS}


def person():
    path = DATA / f"person{EXT}"
    p = read(path)
    if not isinstance(p, dict):
        raise CVError(f"{rel(path)}: expected name, email, phone, location, linkedin and github")
    for key in ("name", "email", "phone", "linkedin", "github"):
        if not isinstance(p.get(key), str) or not p[key].strip():
            raise CVError(f"{rel(path)}: '{key}' is required (as text)")
    for key in ("linkedin", "github"):
        if not p[key].startswith("https://"):
            raise CVError(f"{rel(path)}: '{key}' must start with https://")
    p["location"] = text(p.get("location"), "'location'", path)
    p["languages"] = languages()
    return p


def languages():
    """languages.yaml (optional, the same in every CV): the list shown in each CV language."""
    path = DATA / f"languages{EXT}"
    if not path.exists():
        return {l: [] for l in LANGS}
    data = read(path)
    if not isinstance(data, dict) or any(not isinstance(data.get(l), list) for l in LANGS):
        raise CVError(f"{rel(path)}: needs a list for each language {list(LANGS)} (it can be empty: [])")
    for lang in LANGS:
        for i, item in enumerate(data[lang], 1):
            if not isinstance(item, str) or not item.strip():
                raise CVError(f"{rel(path)}: item {i} in '{lang}' is empty")
    return {l: [" ".join(x.split()) for x in data[l]] for l in LANGS}


NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")


def folders(kind):
    """The CVs of one kind ("bases" or "jobs"): one folder each."""
    root = DATA / kind
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


def cv_names():
    """Every CV: the bases first, then the job CVs."""
    return folders("bases") + folders("jobs")


def files(folder):
    """The files in a folder, without hidden ones (.DS_Store, ...)."""
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))


def parent(folder):
    """A job CV's base: the one file without an extension, named after the base (jobs/acme/data)."""
    marks = [p.name for p in files(folder) if not p.suffix]
    bases = folders("bases")
    if not marks:
        raise CVError(f"{rel(folder)}: no base. Create an empty file named after it ({', '.join(bases)}),"
                      f" e.g.: touch {rel(folder)}/{bases[0] if bases else 'data'}")
    if len(marks) > 1:
        raise CVError(f"{rel(folder)}: a job CV has only one base, found {len(marks)}: {', '.join(marks)}")
    if marks[0] not in bases:
        raise CVError(f"{rel(folder / marks[0])}: there is no base '{marks[0]}' (bases: {', '.join(bases)})")
    return marks[0]


def check_files(folder):
    """Only known files and folders (and, in a job CV, the base): a typo must not go unnoticed."""
    known = {f"{s}{EXT}" for s in SECTIONS}
    for p in files(folder):
        if not p.suffix and folder.parent.name == "bases":
            raise CVError(f"{rel(p)}: a base has no base (only job CVs name one)")
        if p.suffix and p.name not in known:
            raise CVError(f"{rel(p)}: unknown file (a CV folder holds {', '.join(sorted(known))}"
                          f"{' and its base' if folder.parent.name == 'jobs' else ''})")
    for p in folder.iterdir():
        if p.is_dir() and not p.name.startswith(".") and p.name not in FOLDERS:
            raise CVError(f"{rel(p)}: unknown folder (a CV folder can hold {', '.join(f + '/' for f in FOLDERS)})")


def cv(name):
    """The CV's sections and where each one came from: {"base", "sections", "source"}.

    A base has every file section. A job CV has its base (an empty file named after it) and
    only what it changes: a file replaces the base's, skills.yaml and a folder build on the base's.
    """
    base_dir, job_dir = DATA / "bases" / name, DATA / "jobs" / name
    if base_dir.is_dir() and job_dir.is_dir():
        raise CVError(f"'{name}' is both a base and a job CV: rename one of them")
    if not NAME.fullmatch(name):
        raise CVError(f"'{name}': a CV name uses only lowercase letters, digits, '-' and '_'")
    if base_dir.is_dir():
        check_files(base_dir)
        base, chain = None, [base_dir]
        for section in SECTIONS:
            if not (base_dir / f"{section}{EXT}").exists():
                raise CVError(f"{rel(base_dir)}: a base needs every section, '{section}{EXT}' is missing")
    elif job_dir.is_dir():
        check_files(job_dir)
        base = parent(job_dir)
        chain = [job_dir, DATA / "bases" / base]
        cv(base)                                             # the base itself must be valid
    else:
        raise CVError(f"no CV named '{name}' in {rel(DATA)}/ (there are: {', '.join(cv_names())}, or all)")

    sections, source = {}, {}
    for section, check in SECTIONS.items():
        path = next(d / f"{section}{EXT}" for d in chain if (d / f"{section}{EXT}").exists())
        if section == "skills" and base and path.parent == job_dir:   # the job changes the base's lines
            base_path = DATA / "bases" / base / f"skills{EXT}"
            sections[section] = merge_skills(check_skills(read(base_path), base_path), read(path), path)
            source[section] = f"{name}+{base}"
        else:
            sections[section], source[section] = check(read(path), path), path.parent.name
    for kind in FOLDERS:
        base_folder = DATA / "bases" / (base or name) / kind
        inherited = check_folder(kind, base_folder) if base_folder.is_dir() else {"title": None, "items": []}
        if base and (job_dir / kind).is_dir():                       # the job builds on the base's items
            sections[kind] = check_folder(kind, job_dir / kind, inherited)
            source[kind] = f"{name}+{base}" if base_folder.is_dir() else name
        else:
            sections[kind] = inherited
            source[kind] = (base or name) if base_folder.is_dir() else "-"
    return {"base": base, "sections": sections, "source": source}


def check_header(data, path):
    """titles:  pt: A, B, C   /   en: A, B, C   (the same order in both languages)"""
    titles = data.get("titles") if isinstance(data, dict) else None
    if not isinstance(titles, dict):
        raise CVError(f"{rel(path)}: expected 'titles:' with a 'pt:' and an 'en:' line")
    split = {}
    for lang in LANGS:
        line = titles.get(lang)
        if not isinstance(line, str) or not line.strip():
            raise CVError(f"{rel(path)}: titles needs a '{lang}:' line (titles separated by commas)")
        split[lang] = [t.strip() for t in line.split(",") if t.strip()]
    if any(len(t) != TITLES for t in split.values()):
        counts = ", ".join(f"{lang} has {len(t)}" for lang, t in split.items())
        raise CVError(f"{rel(path)}: {counts} (each language needs {TITLES} titles, separated by commas)")
    return {"titles": [{lang: split[lang][i] for lang in LANGS} for i in range(TITLES)]}


def check_summary(data, path):
    return text(data, "the summary", path)


def both(value, where, path):
    """A text that is the same in every language (one line) or not (pt: ... / en: ...)."""
    if isinstance(value, str) and value.strip():
        return {l: " ".join(value.split()) for l in LANGS}
    return text(value, where, path)


def skill_name(value, key, path):
    """'Linguagens, Programming Languages' -> {pt: Linguagens, en: Programming Languages}"""
    parts = [x.strip() for x in value.split(",")] if isinstance(value, str) else []
    if len(parts) != len(LANGS) or not all(parts):
        raise CVError(f"{rel(path)}: '{key}' name needs {len(LANGS)} names separated by a comma "
                      f"({', '.join(LANGS)}), e.g.: Linguagens, Programming Languages"
                      + (f" (found {len(parts)})" if parts else ""))
    return dict(zip(LANGS, parts))


def skill_line(key, value, path, new=True):
    """One skill line: {name, skills}. A new line needs both; a change of a base line, one of them."""
    if not NAME.fullmatch(str(key)):
        raise CVError(f"{rel(path)}: '{key}': a line key uses only lowercase letters, digits, '-' and '_'")
    if not isinstance(value, dict) or not value or set(value) - {"name", "skills"}:
        raise CVError(f"{rel(path)}: '{key}' needs 'name:' and 'skills:'")
    if new and set(value) != {"name", "skills"}:
        raise CVError(f"{rel(path)}: '{key}' is a new line: it needs both 'name:' and 'skills:'")
    line = {}
    if "name" in value:
        line["name"] = skill_name(value["name"], key, path)
    if "skills" in value:
        line["skills"] = both(value["skills"], f"'{key}' skills", path)
    return line


def check_skills(data, path):
    """The skill lines of a base, in order: {key: {name, skills}}."""
    if not isinstance(data, dict) or not data:
        raise CVError(f"{rel(path)}: expected skill lines, e.g.:  langs:  name: ...  skills: ...")
    return {key: skill_line(key, value, path) for key, value in data.items()}


def merge_skills(lines, data, path):
    """A job's skills.yaml over its base's lines: replace (same key), remove (empty key), add (new key)."""
    if not isinstance(data, dict) or not data:
        raise CVError(f"{rel(path)}: expected skill lines (or delete the file to keep the base's)")
    lines = {key: dict(line) for key, line in lines.items()}
    for key, value in data.items():
        if value is None:
            if key not in lines:
                raise CVError(f"{rel(path)}: '{key}' is empty, but the base has no such line "
                              f"(its lines: {', '.join(lines)})")
            del lines[key]
        elif key in lines:
            lines[key].update(skill_line(key, value, path, new=False))
        else:
            lines[key] = skill_line(key, value, path)
    return lines


SECTIONS = {"header": check_header, "summary": check_summary,      # the files of a CV folder, in order
            "skills": check_skills}


# ---------------------------------------------------------------- experiences and education

ORG = {"technical": "institution", "professional": "company"}   # experience folders -> the field that says where
YEAR = re.compile(r"\d{4}")


def month(value, key, path):
    """'2022-08' -> (2022, 8)"""
    found = MONTH.fullmatch(value) if isinstance(value, str) else None
    if not found or not 1 <= int(found.group(2)) <= 12:
        raise CVError(f"{rel(path)}: '{key}' must be a month like 2022-08"
                      f"{' (or present)' if key == 'end' else ''}")
    return int(found.group(1)), int(found.group(2))


def library(kind, item_id, where):
    """The path of one item of the library: <kind>/<id>.yaml (its facts, the same in every CV)."""
    path = DATA / kind / f"{item_id}{EXT}"
    if not path.exists():
        known = sorted(p.stem for p in (DATA / kind).glob(f"*{EXT}")) if (DATA / kind).is_dir() else []
        raise CVError(f"{rel(where)}: no '{item_id}' in {rel(DATA / kind)}/ "
                      f"(there are: {', '.join(known) or 'none yet'})")
    return path


def experience(kind, item_id, where):
    """The facts of one experience: where, start, end (months) and mode."""
    path = library(kind, item_id, where)
    facts = read(path)
    org = ORG[kind]
    if not isinstance(facts, dict):
        raise CVError(f"{rel(path)}: expected {org}, start, end and mode")
    if not isinstance(facts.get(org), str) or not facts[org].strip():
        raise CVError(f"{rel(path)}: '{org}' is required")
    start = month(facts.get("start"), "start", path)
    end = None if facts.get("end") == "present" else month(facts.get("end"), "end", path)
    if end and end < start:
        raise CVError(f"{rel(path)}: 'end' comes before 'start'")
    if facts.get("mode") not in MODES:
        raise CVError(f"{rel(path)}: 'mode' must be one of {', '.join(MODES)}")
    return {"org": facts[org].strip(), "start": start, "end": end, "mode": facts["mode"]}


def view(data, path):
    """How one CV shows an experience: its title and bullets (the same number in every language)."""
    if not isinstance(data, dict):
        raise CVError(f"{rel(path)}: expected 'title:' and 'bullets:'")
    title = text(data.get("title"), "the title", path)
    bullets = data.get("bullets")
    if not isinstance(bullets, dict) or any(not isinstance(bullets.get(l), list) or not bullets[l]
                                            for l in LANGS):
        raise CVError(f"{rel(path)}: 'bullets' needs a list for each language {list(LANGS)}")
    counts = {l: len(bullets[l]) for l in LANGS}
    if len(set(counts.values())) > 1:
        raise CVError(f"{rel(path)}: " + ", ".join(f"{l} has {n} bullets" for l, n in counts.items())
                      + " (the same number in every language)")
    if counts["pt"] > BULLETS:
        raise CVError(f"{rel(path)}: {counts['pt']} bullets, at most {BULLETS} per experience")
    for lang in LANGS:
        for i, b in enumerate(bullets[lang], 1):
            if not isinstance(b, str) or not b.strip():
                raise CVError(f"{rel(path)}: bullet {i} in '{lang}' is empty")
    return {"title": title, "bullets": {l: [" ".join(b.split()) for b in bullets[l]] for l in LANGS}}


def year(value, key, path):
    """2018 -> 2018"""
    if not YEAR.fullmatch(str(value)):
        raise CVError(f"{rel(path)}: '{key}' must be a year like 2018"
                      f"{' (or present)' if key == 'end' else ''}")
    return int(value)


def degree(kind, item_id, where):
    """The facts of one degree: institution and degree (in every language), start and end (years)."""
    path = library(kind, item_id, where)
    facts = read(path)
    if not isinstance(facts, dict):
        raise CVError(f"{rel(path)}: expected institution, degree, start and end")
    start = year(facts.get("start"), "start", path)
    end = None if facts.get("end") == "present" else year(facts.get("end"), "end", path)
    if end and end < start:
        raise CVError(f"{rel(path)}: 'end' comes before 'start'")
    return {"org": text(facts.get("institution"), "'institution'", path),
            "degree": text(facts.get("degree"), "'degree'", path), "start": start, "end": end}


def project(kind, item_id, where):
    """The facts of one project: its name and link."""
    path = library(kind, item_id, where)
    facts = read(path)
    if not isinstance(facts, dict):
        raise CVError(f"{rel(path)}: expected name and link")
    if not isinstance(facts.get("name"), str) or not facts["name"].strip():
        raise CVError(f"{rel(path)}: 'name' is required")
    if not isinstance(facts.get("link"), str) or not facts["link"].startswith("https://"):
        raise CVError(f"{rel(path)}: 'link' is required and must start with https://")
    return {"name": facts["name"].strip(), "link": facts["link"].strip()}


def description(data, path):
    """How one CV shows a degree: a one-line description."""
    if not isinstance(data, dict):
        raise CVError(f"{rel(path)}: expected 'description:' with a 'pt:' and an 'en:' line")
    return {"description": text(data.get("description"), "the description", path)}


def check_folder(kind, folder, base=None):
    """A CV's items of one kind: NN-<id>.yaml files, shown in the NN order, and (only in the
    folders with a title of their own) a required title.yaml, the section title in this CV.

    In a job CV, base is the base's items of this kind: an empty file shows an item as the base
    does, a file with some fields changes only those, and title.yaml is optional."""
    facts, shown, titled, keys = FOLDERS[kind]
    inherited = {i["id"]: i["view"] for i in base["items"]} if base else {}
    items, numbers, title = [], {}, None
    for p in files(folder):
        if p.name == f"title{EXT}":
            if not titled:
                raise CVError(f"{rel(p)}: {kind}/ has no title{EXT} (its title is always the same): delete it")
            title = text(read(p), "the section title", p)
            continue
        found = ITEM.fullmatch(p.name)
        if not found:
            raise CVError(f"{rel(p)}: name it NN-<id>{EXT}, e.g. 01-thesis{EXT} "
                          "(NN is its place in the CV)")
        n, item_id = found.groups()
        if n in numbers:
            raise CVError(f"{rel(folder)}: {numbers[n]} and {p.name} have the same number {n}")
        numbers[n] = p.name
        data = read(p)
        data = {} if data is None else data                          # an empty file
        if not isinstance(data, dict) or set(data) - set(keys):
            raise CVError(f"{rel(p)}: expected {' and '.join(k + ':' for k in keys)}"
                          f"{' (or nothing: as the base shows it)' if base else ''}")
        if item_id in inherited:
            data = {**inherited[item_id], **data}                    # the base's, with the job's changes
        elif base and set(data) != set(keys):
            raise CVError(f"{rel(p)}: the base does not show '{item_id}' in {kind}/, so this file needs "
                          f"{' and '.join(k + ':' for k in keys)}")
        items.append({"n": n, "id": item_id, "view": data, **facts(kind, item_id, p), **shown(data, p)})
    if title is None and base:
        title = base["title"]                                        # the base's section title
    if titled and title is None:
        raise CVError(f"{rel(folder)}: title{EXT} is missing (the section title in this CV, with pt: and en:)")
    return {"title": title, "items": sorted(items, key=lambda i: i["n"])}


FOLDERS = {                                         # the folders of a CV, in order: how to read the
    "technical": (experience, view, True, ("title", "bullets")),       # library item and the CV's
    "professional": (experience, view, True, ("title", "bullets")),    # view, if it has a title.yaml
    "projects": (project, description, False, ("description",)),       # (else: a fixed title) and
    "education": (degree, description, False, ("description",)),
}                                                                       # the fields of its view


# ---------------------------------------------------------------- LaTeX

ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
           "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


LINK = re.compile(r"\[([^\]]+)\]\((https://[^)\s]+)\)")


def esc(s):
    return "".join(ESCAPES.get(c, c) for c in s)


def href(url):
    """A URL as \\href takes it (its % and # escaped)."""
    return url.replace("%", r"\%").replace("#", r"\#")


def rich(s):
    """A text that can hold links: [NASA ADS](https://...) -> \\href{https://...}{NASA ADS}."""
    out, last = [], 0
    for found in LINK.finditer(s):
        out += [esc(s[last:found.start()]), rf"\href{{{href(found.group(2))}}}{{{esc(found.group(1))}}}"]
        last = found.end()
    return "".join(out + [esc(s[last:])])


def short_url(url):
    """https://www.linkedin.com/in/x/ -> linkedin.com/in/x (the visible text of a link)."""
    for prefix in ("https://", "http://", "www."):
        url = url[len(prefix):] if url.startswith(prefix) else url
    return url.rstrip("/")


def contact(icon, url, label, shown):
    return rf"\cvcontact{{{icon}}}{{{url}}}{{{esc(label)}}}{{{esc(shown)}}}"


def period(item, lang):
    """Aug 2022 -- Dec 2023  /  Aug 2022 -- Present"""
    def when(m):
        return f"{MONTHS[lang][m[1] - 1]} {m[0]}"
    return f"{when(item['start'])} -- {when(item['end']) if item['end'] else PRESENT[lang]}"


def experiences(items, lang):
    """\\cvexperience{title}{period}{where}{mode}{\\item ...} for each experience, in order."""
    out = []
    for i in items:
        bullets = " ".join(rf"\item {rich(b)}" for b in i["bullets"][lang])
        out.append(rf"\cvexperience{{{esc(i['title'][lang])}}}{{{period(i, lang)}}}"
                   rf"{{{esc(i['org'])}}}{{{MODES[i['mode']][lang]}}}{{{bullets}}}")
    return "%\n".join(out)


def educations(items, lang):
    """\\cveducation{degree}{years}{institution}{description} for each degree, in order."""
    out = []
    for i in items:
        years = f"{i['start']} -- {i['end'] if i['end'] else PRESENT[lang]}"
        out.append(rf"\cveducation{{{esc(i['degree'][lang])}}}{{{years}}}"
                   rf"{{{esc(i['org'][lang])}}}{{{rich(i['description'][lang])}}}")
    return "%\n".join(out)


def projects(items, lang):
    """\\cvproject{name}{link}{shown link}{description} for each project, in order."""
    return "%\n".join(rf"\cvproject{{{esc(i['name'])}}}{{{href(i['link'])}}}{{{esc(short_url(i['link']))}}}"
                       rf"{{{rich(i['description'][lang])}}}" for i in items)


def section_title(c, kind, lang):
    """The CV's title for a section (its title.yaml; empty if the CV has no such folder)."""
    own = c["sections"][kind]["title"]
    return own[lang] if own else ""


def skill_items(lines, lang):
    """\\cvskill{name}{skills} for each line, in order."""
    return "%\n".join(rf"\cvskill{{{esc(l['name'][lang])}}}{{{esc(l['skills'][lang])}}}"
                       for l in lines.values())


def language_items(p, lang):
    r"""\cvlanguage{...} for each language, in the file's order (the style draws them)."""
    return "".join(rf"\cvlanguage{{{esc(x)}}}" for x in p["languages"][lang])


def content(p, c, lang):
    """One CV in one language, as LaTeX macros. The style (latex/styles/<style>/) draws them."""
    links = [contact("envelope-fill", f"mailto:{p['email']}", p["email"], p["email"]),
             contact("linkedin", p["linkedin"], "LinkedIn", short_url(p["linkedin"])),
             contact("github", p["github"], "GitHub", short_url(p["github"]))]
    titles = c["sections"]["header"]["titles"]
    return "\n".join([
        "% generated by scripts/build.py from the YAML data: edit the data, not this file",
        "",
        "% header",
        rf"\def\HeaderName{{{esc(p['name'])}}}",
        rf"\def\HeaderTitles{{{r'\cvtitlesep '.join(esc(t[lang]) for t in titles)}}}",
        rf"\def\HeaderMeta{{{esc(p['location'][lang])}\cvsep {esc(p['phone'])}}}",
        rf"\def\HeaderLinks{{{r'\cvlinksep '.join(links)}}}",
        "",
        "% summary",
        rf"\def\Summary{{{esc(c['sections']['summary'][lang])}}}",
        "",
        "% technical experience (no items: the section is not shown)",
        rf"\def\TechnicalTitle{{{esc(section_title(c, 'technical', lang))}}}",
        rf"\def\TechnicalItems{{{experiences(c['sections']['technical']['items'], lang)}}}",
        "",
        "% professional experience (no items: the section is not shown)",
        rf"\def\ProfessionalTitle{{{esc(section_title(c, 'professional', lang))}}}",
        rf"\def\ProfessionalItems{{{experiences(c['sections']['professional']['items'], lang)}}}",
        "",
        "% projects (no items: the section is not shown; the title is \\LabelProjects)",
        rf"\def\ProjectsItems{{{projects(c['sections']['projects']['items'], lang)}}}",
        "",
        "% education (no items: the section is not shown)",
        rf"\def\EducationItems{{{educations(c['sections']['education']['items'], lang)}}}",
        "",
        "% skills (the title is \\LabelSkills)",
        rf"\def\SkillsItems{{{skill_items(c['sections']['skills'], lang)}}}",
        "",
        "% languages (empty: the section is not shown)",
        rf"\def\LanguagesItems{{{language_items(p, lang)}}}",
    ]) + "\n"


def language(lang, babel):
    """languages/<lang>.tex: babel and the section titles (\\LabelSummary, ...) in that language."""
    return "\n".join([rf"\usepackage[{babel}]{{babel}}"] +
                     [rf"\def\Label{key}{{{esc(label)}}}" for key, label in LABELS[lang].items()]) + "\n"


def config(names, default):
    lines = [(rf"\providecommand{{\CV}}{{{default}}}", names), (r"\providecommand{\Lang}{pt}", list(LANGS)),
             (r"\providecommand{\Style}{ats}", STYLES)]
    width = max(len(line) for line, _ in lines) + 3
    return "\n".join([
        "% config.tex: which CV main.tex compiles. Change the three values and recompile.",
        "% (scripts/build.py overrides them from the command line to build every PDF.)",
        *([f"% {', '.join(XELATEX)}: compile with XeLaTeX (the others: pdfLaTeX)."] if XELATEX else []),
        "",
        *(f"{line:{width}}% {', '.join(options)}" for line, options in lines),
    ]) + "\n"


# ---------------------------------------------------------------- build

def project(p, cvs):
    """Writes dist/latex/ (latex/ + config.tex + languages/ + content/) and its zip."""
    if PROJECT.exists():
        shutil.rmtree(PROJECT)
    shutil.copytree(LATEX, PROJECT)
    (PROJECT / "config.tex").write_text(config(list(cvs), next(iter(cvs))), encoding="utf-8")
    (PROJECT / "languages").mkdir()
    for lang, babel in LANGS.items():
        (PROJECT / "languages" / f"{lang}.tex").write_text(language(lang, babel), encoding="utf-8")
    (PROJECT / "content").mkdir()
    for name, c in cvs.items():
        for lang in LANGS:
            (PROJECT / "content" / f"{name}-{lang}.tex").write_text(content(p, c, lang), encoding="utf-8")
    zip_path = shutil.make_archive(str(DIST / "cvgit-latex"), "zip", PROJECT)
    return Path(zip_path)


def compile_pdf(name, lang, style):
    """Compiles one PDF from a copy of dist/latex/ and returns (path, pages)."""
    work = DIST / ".build"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(PROJECT, work)
    choice = rf"\def\CV{{{name}}}\def\Lang{{{lang}}}\def\Style{{{style}}}\input{{main.tex}}"
    engine = "xelatex" if style in XELATEX else "pdflatex"
    result = subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error", "-jobname=cv", choice],
                            cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-15:])
        raise CVError(f"{engine} failed for {name}-{lang}-{style} (the files are in {rel(work)}):\n{tail}")
    pdf = DIST / f"{name}-{lang}-{style}.pdf"
    shutil.copyfile(work / "cv.pdf", pdf)
    shutil.rmtree(work)
    found = re.search(r"Output written on cv\.pdf \((\d+) pages?", result.stdout)
    return pdf, int(found.group(1)) if found else 0


def describe(name, c):
    """acme (base: data)  ->  header: acme  summary: data  technical: data"""
    kind = f" (base: {c['base']})" if c["base"] else ""
    return f"{name}{kind}  ->  " + "  ".join(f"{s}: {c['source'][s]}" for s in [*SECTIONS, *FOLDERS])


def main():
    args = [a for a in sys.argv[1:] if a != "--example"]
    if not args or args[0] in ("-h", "--help") or len(args) > 2 or (len(args) == 2 and args[1] not in LANGS):
        sys.exit(__doc__.strip().splitlines()[0])
    name, langs = args[0], [args[1]] if len(args) == 2 else list(LANGS)
    try:
        p = person()
        cvs = {n: cv(n) for n in cv_names()}             # all of them: the LaTeX project has every CV
        if name != "all" and name not in cvs:
            cv(name)                                     # raises the "no CV named" error
        print(f"data: {rel(DATA)}/")
        DIST.mkdir(parents=True, exist_ok=True)
        zip_path = project(p, cvs)
        print(f"ok  {rel(PROJECT)}/  and  {rel(zip_path)}  (a LaTeX project: choose the CV in config.tex)")
        for n in (cvs if name == "all" else [name]):
            print(describe(n, cvs[n]))
            for lang in langs:
                for style in STYLES:
                    pdf, pages = compile_pdf(n, lang, style)
                    print(f"ok  {rel(pdf)}  ({pages} page{'s' * (pages != 1)})")
    except CVError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
