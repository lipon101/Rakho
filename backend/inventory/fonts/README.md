# Embedded fonts

These two files are shipped with the code and embedded into every invoice and
quotation PDF, so a document renders correctly on a machine that has no Bengali
font installed — which is most machines outside Bangladesh.

## Why Hind Siliguri

The first font chosen for this module was **Noto Sans Bengali**, and it was
wrong in a way that is easy to miss: its `cmap` maps the Bengali block and the
Bengali digits, and **nothing in `A–Z`**. A document set entirely in it renders
every Latin word — the brand name, the customer's legal name, "Base plan" — as
*blank space*. Not boxes, not a fallback: nothing. The page still looks
finished, which is what makes it dangerous.

Hind Siliguri carries both scripts in one file, so a mixed Bengali/English
invoice needs no font switching and no second font embedded. The regression is
guarded by `test_latin_text_renders_in_the_bengali_document`.

## Licence

Hind Siliguri is released under the **SIL Open Font License 1.1**, which permits
embedding in documents and redistribution with software. The copyright notice
is retained in the font files themselves.

- Upstream: https://github.com/google/fonts/tree/main/ofl/hindsiliguri
- Designer: Indian Type Foundry
