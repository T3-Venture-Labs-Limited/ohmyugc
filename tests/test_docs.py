import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_and_images_point_at_real_files():
    text = (ROOT / "README.md").read_text()
    targets = re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text) + re.findall(r'src="([^"]+)"', text)
    local = [t for t in targets if not t.startswith(("http://", "https://", "mailto:"))]
    assert local, "the README should link to its docs and images"
    missing = [t for t in local if not (ROOT / t).exists()]
    assert not missing, f"README points at files that do not exist: {missing}"


def test_readme_anchors_exist():
    text = (ROOT / "README.md").read_text()
    headings = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
        for h in re.findall(r"^#+\s+(.+)$", text, re.M)
    }
    contributing = (ROOT / "CONTRIBUTING.md").read_text()
    contributing_headings = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
        for h in re.findall(r"^#+\s+(.+)$", contributing, re.M)
    }
    for anchor in re.findall(r"\]\(#([^)]+)\)", text):
        assert anchor in headings, f"README anchor #{anchor} has no heading"
    for anchor in re.findall(r"\]\(CONTRIBUTING\.md#([^)]+)\)", text):
        assert anchor in contributing_headings, f"CONTRIBUTING.md has no heading for #{anchor}"


def test_readme_cli_flags_exist():
    """Every `omu ...` line in the README parses with the real argument parser."""
    import shlex

    from oh_my_ugc import cli

    text = (ROOT / "README.md").read_text()
    parser = cli.build()
    lines = [
        line.strip()
        for block in re.findall(r"```bash\n(.*?)```", text, re.S)
        for line in block.splitlines()
        if line.strip().startswith("omu ")
    ]
    assert len(lines) >= 8
    for line in lines:
        argv = shlex.split(line.split("#")[0])[1:]
        args = parser.parse_args(argv)  # raises SystemExit on a flag that does not exist
        assert args.func


def test_openspec_change_validates():
    import shutil
    import subprocess

    if shutil.which("openspec") is None:
        return
    proc = subprocess.run(
        ["openspec", "validate", "add-oh-my-ugc-v1", "--strict"], cwd=ROOT, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
