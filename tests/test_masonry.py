from hatui.masonry import column_layout


def test_column_count_is_responsive_with_minimum_width() -> None:
    assert column_layout(40, 44, 1) == (1, 40)
    assert column_layout(90, 44, 1) == (2, 44)
    assert column_layout(200, 44, 1)[0] == 4
    assert column_layout(0, 44, 1)[0] == 1
