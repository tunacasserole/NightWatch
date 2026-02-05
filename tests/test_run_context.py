"""Tests for RunContext accumulation (Ralph pattern: cross-error knowledge sharing)."""

from nightwatch.models import RunContext


class TestRunContextEmpty:
    """Empty context produces empty string."""

    def test_empty_context_returns_empty_string(self):
        ctx = RunContext()
        assert ctx.to_prompt_section() == ""

    def test_empty_context_with_custom_max_chars(self):
        ctx = RunContext()
        assert ctx.to_prompt_section(max_chars=500) == ""


class TestRecordAnalysis:
    """record_analysis() appends to errors_analyzed."""

    def test_record_analysis_basic(self):
        ctx = RunContext()
        ctx.record_analysis("NoMethodError", "Controller/products/show", "Missing nil check")
        assert len(ctx.errors_analyzed) == 1
        assert "NoMethodError in Controller/products/show" in ctx.errors_analyzed[0]
        assert "Missing nil check" in ctx.errors_analyzed[0]

    def test_record_analysis_no_summary(self):
        ctx = RunContext()
        ctx.record_analysis("RuntimeError", "Worker/jobs/process", "")
        assert ctx.errors_analyzed[0] == "RuntimeError in Worker/jobs/process"

    def test_record_analysis_truncates_summary(self):
        ctx = RunContext()
        long_summary = "x" * 200
        ctx.record_analysis("Error", "tx", long_summary)
        # Summary truncated to 100 chars
        assert len(ctx.errors_analyzed[0]) < 200

    def test_record_multiple_analyses(self):
        ctx = RunContext()
        ctx.record_analysis("Err1", "tx1", "cause1")
        ctx.record_analysis("Err2", "tx2", "cause2")
        ctx.record_analysis("Err3", "tx3", "cause3")
        assert len(ctx.errors_analyzed) == 3


class TestRecordFile:
    """record_file() adds to files_examined."""

    def test_record_file_basic(self):
        ctx = RunContext()
        ctx.record_file("app/models/user.rb", "User model with validations")
        assert "app/models/user.rb" in ctx.files_examined
        assert ctx.files_examined["app/models/user.rb"] == "User model with validations"

    def test_record_file_truncates_summary(self):
        ctx = RunContext()
        long_summary = "a" * 200
        ctx.record_file("some/path.rb", long_summary)
        assert len(ctx.files_examined["some/path.rb"]) <= 80

    def test_record_file_overwrites_existing(self):
        ctx = RunContext()
        ctx.record_file("app/models/user.rb", "first summary")
        ctx.record_file("app/models/user.rb", "updated summary")
        assert ctx.files_examined["app/models/user.rb"] == "updated summary"


class TestToPromptSection:
    """to_prompt_section() formats context as a prompt section."""

    def test_includes_header(self):
        ctx = RunContext()
        ctx.record_analysis("Err", "tx", "cause")
        section = ctx.to_prompt_section()
        assert "## Codebase Context from Previous Analyses" in section

    def test_includes_errors_section(self):
        ctx = RunContext()
        ctx.record_analysis("NoMethodError", "tx", "nil check missing")
        section = ctx.to_prompt_section()
        assert "### Errors Already Analyzed" in section
        assert "NoMethodError in tx" in section

    def test_includes_patterns_section(self):
        ctx = RunContext()
        ctx.patterns_discovered.append("Uses ActiveRecord callbacks")
        section = ctx.to_prompt_section()
        assert "### Codebase Patterns Discovered" in section
        assert "Uses ActiveRecord callbacks" in section

    def test_includes_files_section(self):
        ctx = RunContext()
        ctx.record_file("app/models/user.rb", "User model")
        section = ctx.to_prompt_section()
        assert "### Key Files Examined" in section
        assert "`app/models/user.rb`" in section

    def test_all_sections_present(self):
        ctx = RunContext()
        ctx.record_analysis("Err", "tx", "cause")
        ctx.patterns_discovered.append("pattern1")
        ctx.record_file("file.rb", "desc")
        section = ctx.to_prompt_section()
        assert "### Errors Already Analyzed" in section
        assert "### Codebase Patterns Discovered" in section
        assert "### Key Files Examined" in section

    def test_caps_errors_at_five(self):
        ctx = RunContext()
        for i in range(8):
            ctx.record_analysis(f"Err{i}", f"tx{i}", f"cause{i}")
        section = ctx.to_prompt_section()
        # Only last 5 should appear
        assert "Err3" in section
        assert "Err7" in section
        # Err0, Err1, Err2 should be excluded (oldest)
        assert "Err0" not in section
        assert "Err1" not in section
        assert "Err2" not in section

    def test_caps_patterns_at_five(self):
        ctx = RunContext()
        for i in range(8):
            ctx.patterns_discovered.append(f"pattern_{i}")
        section = ctx.to_prompt_section()
        assert "pattern_7" in section
        assert "pattern_3" in section
        assert "pattern_0" not in section
        assert "pattern_1" not in section
        assert "pattern_2" not in section

    def test_caps_files_at_ten(self):
        ctx = RunContext()
        for i in range(15):
            ctx.record_file(f"file_{i}.rb", f"desc_{i}")
        section = ctx.to_prompt_section()
        assert "file_14.rb" in section
        assert "file_5.rb" in section
        # First 5 should be excluded
        assert "file_0.rb" not in section
        assert "file_4.rb" not in section


class TestTruncation:
    """to_prompt_section() truncates at max_chars."""

    def test_truncation_appends_marker(self):
        ctx = RunContext()
        # Add enough content to exceed a small limit
        for i in range(10):
            ctx.record_file(f"app/models/very_long_path_{i}/model.rb", f"Description {i}")
            ctx.record_analysis(f"ErrorClass{i}", f"Transaction/path/{i}", f"Some cause {i}")
        section = ctx.to_prompt_section(max_chars=200)
        assert len(section) <= 200
        assert "[...truncated]" in section

    def test_no_truncation_when_under_limit(self):
        ctx = RunContext()
        ctx.record_analysis("Err", "tx", "cause")
        section = ctx.to_prompt_section(max_chars=5000)
        assert "[...truncated]" not in section
