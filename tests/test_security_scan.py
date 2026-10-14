import subprocess

from scripts.security_scan import scan


def test_unicode_untracked_source_is_scanned(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    folder = repo / "中文目录"
    folder.mkdir()
    (folder / "说明.md").write_text("credential: " + "A" * 32, encoding="utf-8")
    findings = scan(repo)
    assert any("中文目录/说明.md" in item and "疑似AK" in item for item in findings)


def test_non_git_source_archive_is_scanned_and_nonempty_assignment_is_rejected(tmp_path):
    (tmp_path / ".env.example").write_text("BAIDU_MAP_AK=\nBAIDU_API_QPS=2\n", encoding="utf-8")
    assert scan(tmp_path) == []
    (tmp_path / "README.md").write_text("BAIDU_MAP_AK=short-test-value\n", encoding="utf-8")
    assert any("AK赋值" in item for item in scan(tmp_path))


def test_government_document_id_exception_only_applies_inside_its_url(tmp_path):
    token = "abcdef01" * 4
    file = tmp_path / "README.md"
    file.write_text(f"https://example.gov.cn/docs/{token}.html\n", encoding="utf-8")
    assert scan(tmp_path) == []
    file.write_text(file.read_text(encoding="utf-8") + f"credential: {token}\n", encoding="utf-8")
    assert any("疑似AK" in item for item in scan(tmp_path))
