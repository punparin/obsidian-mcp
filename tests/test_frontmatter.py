from obsidian_mcp.frontmatter import get_frontmatter, update_frontmatter, has_frontmatter, get_body


class TestHasFrontmatter:
    def test_with_frontmatter(self):
        assert has_frontmatter("---\ntitle: Test\n---\nBody")

    def test_without_frontmatter(self):
        assert not has_frontmatter("# Just a heading\n\nBody text")

    def test_empty(self):
        assert not has_frontmatter("")


class TestGetFrontmatter:
    def test_basic(self):
        content = "---\ntitle: My Note\ntags: [a, b]\n---\nBody"
        fm = get_frontmatter(content)
        assert fm["title"] == "My Note"
        assert fm["tags"] == ["a", "b"]

    def test_no_frontmatter(self):
        assert get_frontmatter("No frontmatter here") == {}

    def test_tags_as_string(self):
        content = "---\ntags: \"a, b, c\"\n---\nBody"
        fm = get_frontmatter(content)
        assert fm["tags"] == ["a", "b", "c"]

    def test_tags_as_list(self):
        content = "---\ntags:\n  - one\n  - two\n---\nBody"
        fm = get_frontmatter(content)
        assert fm["tags"] == ["one", "two"]


class TestUpdateFrontmatter:
    def test_merge_updates(self):
        content = "---\ntitle: Old\nstatus: draft\n---\nBody text"
        result = update_frontmatter(content, {"status": "active"})
        fm = get_frontmatter(result)
        assert fm["title"] == "Old"
        assert fm["status"] == "active"

    def test_preserves_body(self):
        content = "---\ntitle: Test\n---\nMy body content\n\nSecond paragraph"
        result = update_frontmatter(content, {"title": "Updated"})
        assert "My body content" in result
        assert "Second paragraph" in result

    def test_remove_key_with_none(self):
        content = "---\ntitle: Test\nstatus: draft\n---\nBody"
        result = update_frontmatter(content, {"status": None})
        fm = get_frontmatter(result)
        assert "status" not in fm
        assert fm["title"] == "Test"

    def test_add_frontmatter_to_bare_content(self):
        content = "Just some text"
        result = update_frontmatter(content, {"title": "New"})
        fm = get_frontmatter(result)
        assert fm["title"] == "New"
        assert "Just some text" in result


class TestGetBody:
    def test_with_frontmatter(self):
        content = "---\ntitle: Test\n---\nBody content here"
        assert "Body content here" in get_body(content)

    def test_without_frontmatter(self):
        content = "No frontmatter, just content"
        assert "No frontmatter" in get_body(content)
