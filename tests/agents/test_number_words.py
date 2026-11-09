from app.orchestrator.agents.number_words import words_to_digits


def test_words_to_digits():
    assert words_to_digits("поменяй местами кадры три и четыре") == "поменяй местами кадры 3 и 4"
    assert words_to_digits("создай два ролика") == "создай 2 ролика"
    assert words_to_digits("один проект") == "1 проект"
    assert words_to_digits("двадцать секунд") == "20 секунд"
    # Word substrings should not be replaced
    assert words_to_digits("родина") == "родина"
    assert words_to_digits("подвал") == "подвал"
