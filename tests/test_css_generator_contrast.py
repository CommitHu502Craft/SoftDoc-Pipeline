from modules.css_generator import CSSGenerator


def test_palette_contrast_guard_for_body_and_sidebar():
    generator = CSSGenerator()
    palette = generator._sanitize_palette(
        {
            "primary_color": "#7f7f7f",
            "secondary_color": "#f4f4f4",
            "accent_color": "#eaeaea",
            "background_color": "#f7f7f7",
            "text_color": "#f5f5f5",
        }
    )

    assert generator._contrast_ratio(palette["text"], palette["background"]) >= 4.5
    assert generator._contrast_ratio(palette["sidebar_text"], palette["secondary"]) >= 4.5


def test_palette_accent_fallback_when_too_close_to_background():
    generator = CSSGenerator()
    palette = generator._sanitize_palette(
        {
            "primary_color": "#2563eb",
            "accent_color": "#f8fafc",
            "background_color": "#f8fafc",
        }
    )
    # accent 与背景过近时，回退主色以避免按钮/高亮不可见
    assert palette["accent"] == palette["primary"]
