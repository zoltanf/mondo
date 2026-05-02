# Strict round-trip input

This document uses only block types that the markdown↔doc converter supports cleanly: headings (h1–h3), paragraphs, bullet lists, numbered lists, blockquotes, code blocks with a language tag, and horizontal rules.

## Section A

A short paragraph.

- bullet item one
- bullet item two
- bullet item three

## Section B

1. first numbered step
2. second numbered step
3. third numbered step

### A nested heading

> A blockquote line.

```python
def hello() -> str:
    return "world"
```

---

End of strict input.
