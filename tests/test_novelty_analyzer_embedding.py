from core.novelty_analyzer import NoveltyAnalyzer


def test_novelty_report_contains_embedding_key_by_default():
    analyzer = NoveltyAnalyzer({"seed.py": "def foo(x):\n    return x + 1\n"}, "python")
    report = analyzer.evaluate("def bar(y):\n    return y + 2\n")
    assert "embedding_similarity" in report["seed_best_match"]
    assert "embedding_similarity" in report["source_similarity"]


def test_enable_embedding_mode_fails_open_when_model_unavailable():
    analyzer = NoveltyAnalyzer(
        {"seed.py": "def foo(x):\n    return x + 1\n"},
        "python",
        enable_embedding=True,
        embedding_model_name="__missing_model_for_test__",
        embedding_weight=0.2,
    )
    report = analyzer.evaluate("def bar(y):\n    return y + 2\n")
    assert "novelty_score" in report
    assert "embedding_similarity" in report["seed_best_match"]


def test_embedding_blend_requires_pair_vectors():
    analyzer = NoveltyAnalyzer({"seed.py": "def foo(x):\n    return x + 1\n"}, "python")
    analyzer._embedder = object()
    analyzer.embedding_weight = 0.2

    profile_a = {"token_grams": {"a b c"}, "skeleton": {"s1"}, "identifiers": {"foo"}}
    profile_b = {"token_grams": {"a b c"}, "skeleton": {"s1"}, "identifiers": {"foo"}}

    score = analyzer._pair_similarity(profile_a, profile_b)
    assert score["blended_similarity"] == 0.57
