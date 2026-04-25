"""Chunker tests — heading splits, size packing, micro-chunk merging."""

from obsidian_mcp.chunker import Chunk, chunk_body


class TestHeadingSplits:
    def test_empty_body_returns_nothing(self):
        assert chunk_body("") == []
        assert chunk_body("   \n  \n") == []

    def test_single_section_without_headings(self):
        body = "Just a paragraph of text. Nothing fancy here."
        chunks = chunk_body(body, min_chars=10)
        assert len(chunks) == 1
        assert chunks[0].heading == ""
        assert "Just a paragraph" in chunks[0].text

    def test_h2_sections_become_separate_chunks(self):
        body = (
            "## Context\n\n"
            + "A" * 300
            + "\n\n"
            + "## Constraints\n\n"
            + "B" * 300
        )
        chunks = chunk_body(body, max_chars=1000, min_chars=50)
        headings = [c.heading for c in chunks]
        assert "Context" in headings
        assert "Constraints" in headings

    def test_nested_headings_build_breadcrumbs(self):
        body = (
            "## Context\n\n"
            + "A" * 300
            + "\n\n"
            + "### Background\n\n"
            + "B" * 300
        )
        chunks = chunk_body(body, max_chars=1000, min_chars=50)
        headings = [c.heading for c in chunks]
        assert "Context > Background" in headings

    def test_leading_prose_before_first_heading_preserved(self):
        body = (
            "Lead-in paragraph that has no heading.\n\n"
            "More lead-in." + "\n\n"
            "## First Section\n\nHere.\n"
        )
        chunks = chunk_body(body, max_chars=1000, min_chars=10)
        headings = [c.heading for c in chunks]
        assert "" in headings  # the lead-in is a chunk with empty breadcrumb


class TestSizePacking:
    def test_oversized_section_fans_out(self):
        paragraphs = ["paragraph " + str(i) + " " + ("x" * 800) for i in range(3)]
        body = "## Big Section\n\n" + "\n\n".join(paragraphs)
        chunks = chunk_body(body, max_chars=1600, min_chars=50, overlap_chars=0)
        # 3 paragraphs of ~800 chars each in a 1600-char budget -> expect >= 2 chunks
        assert len(chunks) >= 2
        for ch in chunks:
            assert ch.heading == "Big Section"
            assert len(ch.text) <= 1700  # budget + some slack for headers/joins

    def test_overlap_tail_seeds_next_chunk(self):
        body = "## S\n\n" + ("first paragraph. " * 80) + "\n\n" + ("second paragraph. " * 80)
        chunks = chunk_body(body, max_chars=1200, min_chars=50, overlap_chars=100)
        assert len(chunks) >= 2
        # Second chunk should begin with a tail from the first (overlap).
        tail_of_first = chunks[0].text[-80:]
        assert tail_of_first.strip()[:20] in chunks[1].text


class TestMicroMerge:
    def test_short_section_merges_into_next(self):
        body = (
            "## Tiny\n\nshort.\n\n"
            "## Real\n\n" + ("real content. " * 40)
        )
        chunks = chunk_body(body, max_chars=1600, min_chars=200)
        # 'Tiny' section is ~6 chars of text — should have merged away.
        headings = [c.heading for c in chunks]
        assert "Tiny" not in headings or len(chunks) == 1
        # Content from both sections shows up in exactly one chunk.
        assert any("short" in c.text and "real content" in c.text for c in chunks)

    def test_trailing_micro_absorbed_by_previous(self):
        body = "## Real\n\n" + ("real content. " * 40) + "\n\n## Tiny\n\nbye.\n"
        chunks = chunk_body(body, max_chars=1600, min_chars=200)
        # Final trailing micro-chunk should be pulled into the previous chunk,
        # not live as its own standalone entry.
        assert not any(c.text.strip() == "bye." for c in chunks)
        assert any("bye" in c.text for c in chunks)


class TestOffsets:
    def test_offsets_point_into_original_body(self):
        body = "## A\n\n" + "aaaa\n\n" + "## B\n\n" + "bbbb\n"
        chunks = chunk_body(body, max_chars=1000, min_chars=1)
        # Every chunk's [start:end] slice should contain its own text content.
        for ch in chunks:
            slice_ = body[ch.char_start : ch.char_end]
            # chunk.text is .strip()'d; the slice is the raw span, so the
            # stripped text should be a substring of the raw slice.
            assert ch.text.strip() in slice_


class TestDataclass:
    def test_chunk_is_immutable(self):
        c = Chunk(heading="x", char_start=0, char_end=1, text="a")
        try:
            c.text = "b"  # type: ignore[misc]
        except Exception:
            return
        assert False, "Chunk should be frozen"
