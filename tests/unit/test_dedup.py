"""Tests for deduplication — exact hash and MinHash near-dup (CLEAN-03)."""

from knowledge_lake.pipeline.clean import compute_minhash, remove_boilerplate


def test_identical_docs_jaccard_1() -> None:
    """Two MinHash signatures of the same text should have Jaccard similarity 1.0."""
    text = "The quick brown fox jumps over the lazy dog and the lazy cat"
    m1 = compute_minhash(text, num_perm=128)
    m2 = compute_minhash(text, num_perm=128)
    assert m1.jaccard(m2) == 1.0


def test_different_docs_jaccard_low() -> None:
    """Two completely unrelated strings must have Jaccard similarity below 0.3."""
    m1 = compute_minhash(
        "Quantum mechanics describes the behavior of particles at the subatomic scale",
        num_perm=128,
    )
    m2 = compute_minhash(
        "The administrative safeguards of the HIPAA Security Rule require covered entities",
        num_perm=128,
    )
    assert m1.jaccard(m2) < 0.3


def test_near_duplicate_jaccard_high() -> None:
    """A document with only a few words changed should have high Jaccard similarity."""
    original = " ".join(
        [
            "The patient presents with hypertension and requires treatment for high blood pressure.",
            "Medication adherence is critical for controlling the condition.",
            "The physician recommends a low-sodium diet and regular exercise.",
            "Follow-up appointment scheduled for next month to review lab results.",
            "The patient should monitor blood pressure daily using a home monitor.",
            "Additional tests may be ordered if the pressure does not improve.",
            "The care team will coordinate with the specialist for further evaluation.",
            "Insurance authorization has been obtained for the recommended treatment.",
            "The patient was counseled on the importance of medication compliance.",
            "All instructions were provided in both written and verbal form.",
        ]
    )
    # Change just 3 words
    near_dup = original.replace("hypertension", "high-blood-pressure").replace(
        "critical", "essential"
    ).replace("physician", "doctor")

    m1 = compute_minhash(original, num_perm=128)
    m2 = compute_minhash(near_dup, num_perm=128)
    assert m1.jaccard(m2) >= 0.7


def test_minhash_short_text_no_crash() -> None:
    """compute_minhash on very short text must not raise."""
    m = compute_minhash("hi", num_perm=64)
    from datasketch import MinHash
    assert isinstance(m, MinHash)


def test_shingle_size_configurable() -> None:
    """compute_minhash with custom shingle_size must not raise."""
    m = compute_minhash("one two three four five six seven", num_perm=64, shingle_size=3)
    from datasketch import MinHash
    assert isinstance(m, MinHash)


def test_boilerplate_before_minhash_reduces_false_positives() -> None:
    """Boilerplate removal before MinHash should lower similarity of non-duplicate docs.

    Two documents with identical navigation boilerplate but different body text
    should have lower Jaccard similarity after boilerplate removal than before.
    This demonstrates that boilerplate inflation is avoided (Pitfall 3).
    """
    nav_boilerplate = "Home\n\nAbout Us\n\nContact\n\nPage 1 of 10\n\n"

    body_a = " ".join([
        "The HIPAA Security Rule establishes national standards for protecting",
        "electronic protected health information ePHI that is created received",
        "used or maintained by a covered entity the Security Rule requires",
        "appropriate administrative physical and technical safeguards to ensure",
        "the confidentiality integrity and security of ePHI",
    ])

    body_b = " ".join([
        "Diabetes mellitus type two is a chronic metabolic disorder characterized",
        "by elevated blood sugar insulin resistance and relative insulin deficiency",
        "patients with this condition often require lifestyle modifications including",
        "dietary changes physical activity and may need oral hypoglycemic agents",
        "regular monitoring of hemoglobin A1c is essential for disease management",
    ])

    doc_a_raw = nav_boilerplate + body_a
    doc_b_raw = nav_boilerplate + body_b

    # Similarity before boilerplate removal (boilerplate inflates it)
    m_a_raw = compute_minhash(doc_a_raw, num_perm=128)
    m_b_raw = compute_minhash(doc_b_raw, num_perm=128)
    jaccard_raw = m_a_raw.jaccard(m_b_raw)

    # Similarity after boilerplate removal
    doc_a_clean = remove_boilerplate(doc_a_raw)
    doc_b_clean = remove_boilerplate(doc_b_raw)
    m_a_clean = compute_minhash(doc_a_clean, num_perm=128)
    m_b_clean = compute_minhash(doc_b_clean, num_perm=128)
    jaccard_clean = m_a_clean.jaccard(m_b_clean)

    # After boilerplate removal, similarity should be lower
    assert jaccard_clean < jaccard_raw, (
        f"Expected lower Jaccard after boilerplate removal: "
        f"raw={jaccard_raw:.3f}, clean={jaccard_clean:.3f}"
    )
