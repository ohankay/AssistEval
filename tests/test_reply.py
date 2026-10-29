from assisteval.simulator.reply import parse_reply


def test_text_buttons_and_cards():
    raw = [
        {"text": "Size özel kampanyalar:", "buttons": [{"title": "Ana Menü", "payload": "/menu"}]},
        {"custom": {"cards": [
            {"title": "Market", "subtitle": "%10 iade", "buttons": [{"title": "Detay", "payload": "/detay{1}"}]},
            {"title": "Akaryakıt", "subtitle": "puan", "buttons": [{"title": "Detay", "payload": "/detay{2}"}]},
        ]}},
    ]
    reply = parse_reply(raw)
    assert reply.texts == ["Size özel kampanyalar:", "[Kart] Market - %10 iade", "[Kart] Akaryakıt - puan"]
    assert [b.title for b in reply.buttons] == ["Ana Menü", "Market › Detay", "Akaryakıt › Detay"]
    assert reply.find_button("Akaryakıt › Detay").payload == "/detay{2}"
    assert reply.find_button("detay").payload == "/detay{1}"  # içerir eşleşmesi: ilk uyan
    assert reply.find_button("/menu").title == "Ana Menü"  # aksiyonla da bulunur
    assert reply.find_button("Yok") is None


def test_unknown_shapes_are_tolerated():
    reply = parse_reply({"Data": {"Message": "Merhaba", "QuickReplies": ["Evet", "Hayır"]}})
    assert reply.texts == ["Merhaba"]
    assert [(b.title, b.payload) for b in reply.buttons] == [("Evet", "Evet"), ("Hayır", "Hayır")]
    assert parse_reply("düz metin").text == "düz metin"
