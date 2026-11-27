from app.security import detect_sensitive, luhn_ok, mask_text


def test_rrn_full_and_masked():
    assert detect_sensitive("scan.pdf", "본인 홍길동 000101-3123456").sensitive
    assert detect_sensitive("scan.pdf", "본인 홍길동 000101-3******").sensitive
    assert not detect_sensitive("memo.txt", "연락처 010-1234-5678").sensitive


def test_card_requires_luhn():
    assert luhn_ok("4111 1111 1111 1111")
    assert detect_sensitive("a.txt", "카드 4111-1111-1111-1111").sensitive
    assert not detect_sensitive("a.txt", "주문번호 1234-5678-1234-5678").sensitive


def test_account_needs_context():
    assert detect_sensitive("a.pdf", "계좌번호: 123-456-789012 예금주 홍길동").sensitive
    assert not detect_sensitive("a.pdf", "강의실 123-456-789012 호").sensitive


def test_keywords_in_name_and_head_only():
    check = detect_sensitive("가족관계증명서_2026.pdf")
    assert check.sensitive and "가족관계증명서" in check.reason
    assert detect_sensitive("scan.pdf", "주민등록등본\n발급일 2026-11-01").sensitive
    # 강의자료 본문 뒤쪽에 나온 단어는 민감 서류로 보지 않는다
    lecture = "개인정보 보호 강의\n" + "개인정보 보호법을 배웁니다. " * 40 + "신분증 사본 요구는 최소화해야 합니다."
    assert not detect_sensitive("week5.pdf", lecture).sensitive


def test_extra_keywords():
    assert detect_sensitive("성적증명서.pdf", "", ["성적증명서"]).sensitive
    assert not detect_sensitive("성적증명서.pdf", "", []).sensitive


def test_mask_text():
    text = "연락처 010-1234-5678, 메일 hong@example.com, 계좌 123-456-789012(예금주 홍길동), 000101-3123456"
    masked, n = mask_text(text)
    assert "010-1234-5678" not in masked and "hong@example.com" not in masked
    assert "123-456-789012" not in masked and "000101-3123456" not in masked
    assert n == 4
