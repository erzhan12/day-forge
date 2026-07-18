"""Icon-link parity between the two ``base.html`` render branches.

``base.html`` splits on ``vite_dev_mode`` (see
``day_forge/context_processors.py``): the dev branch points at the Vite
dev server, the prod branch at ``{% static %}``. Every icon must be
declared in *both* branches with the same filename and ``sizes``, and
the underlying file must exist in ``frontend/public/`` (Vite's
``publicDir``, copied verbatim into ``dist/`` on build).

Nothing else enforces this: the default ``StaticFilesStorage`` resolves
``{% static %}`` by string join, so a missing or renamed asset produces
a live 404 rather than any build- or test-time error.
"""

import re
import struct

import pytest
from django.conf import settings
from django.template.loader import render_to_string

PUBLIC_DIR = settings.PROJECT_ROOT / "frontend" / "public"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

EXPECTED_ICON_COUNT = 4

DEV_ORIGIN = "http://localhost:5173/"

# Requires the attribute order rel -> sizes -> href. Reordering them in
# base.html yields zero matches, which surfaces as the count assertion in
# _icon_links failing with "expected 4 icon links, parsed 0" rather than as
# anything that names attribute order — check the template first if you see it.
LINK_RE = re.compile(
    r'<link\s+rel="(?P<rel>icon|apple-touch-icon)"[^>]*?'
    r'sizes="(?P<sizes>[^"]+)"[^>]*?'
    r'href="(?P<href>[^"]+)"',
)


def _icon_links(vite_dev_mode):
    """Render ``base.html`` and return ``[(rel, sizes, href), ...]``.

    Asserts the expected link count up front so that a template or regex
    change which stops matching fails loudly here, rather than letting
    every per-link assertion below pass vacuously over an empty list.
    """
    html = render_to_string("base.html", {"vite_dev_mode": vite_dev_mode})
    links = [
        (m.group("rel"), m.group("sizes"), m.group("href")) for m in LINK_RE.finditer(html)
    ]
    assert len(links) == EXPECTED_ICON_COUNT, (
        f"expected {EXPECTED_ICON_COUNT} icon links, parsed {len(links)}"
        " — if 0, check attribute order in base.html (LINK_RE needs rel -> sizes -> href)"
    )
    return links


def _icon_specs(vite_dev_mode):
    """``{(rel, sizes, filename), ...}`` — the branch-independent contract.

    ``rel`` is part of the tuple so that demoting ``apple-touch-icon`` to a
    plain ``icon`` (in both branches, which parity alone would allow) fails.
    """
    specs = [
        (rel, sizes, href.rsplit("/", 1)[-1]) for rel, sizes, href in _icon_links(vite_dev_mode)
    ]
    # Deduping into a set below would otherwise let a branch that repeats
    # one icon and drops another still satisfy the count and parity checks.
    assert len(set(specs)) == len(specs), f"duplicate icon links: {specs}"
    return set(specs)


def _png_dimensions(path):
    """Return ``(width, height)`` from a PNG's IHDR chunk.

    Stdlib-only (no Pillow dependency): the 8-byte signature is followed
    by a 4-byte chunk length, the ``IHDR`` tag, then two big-endian
    uint32s.
    """
    header = path.read_bytes()[:24]
    assert header[:8] == PNG_SIGNATURE, f"{path.name} is not a PNG"
    assert header[12:16] == b"IHDR", f"{path.name} has no leading IHDR chunk"
    return struct.unpack(">II", header[16:24])


class TestBaseTemplateIcons:
    def test_dev_and_prod_branches_declare_the_same_icons(self):
        assert _icon_specs(vite_dev_mode=True) == _icon_specs(vite_dev_mode=False)

    @pytest.mark.parametrize("vite_dev_mode", [True, False])
    def test_exactly_one_apple_touch_icon_is_declared(self, vite_dev_mode):
        # iOS home-screen icon: a distinct rel, not interchangeable with
        # rel="icon". Parity across branches would not notice it changing.
        rels = [rel for rel, _sizes, _f in _icon_specs(vite_dev_mode)]
        assert rels.count("apple-touch-icon") == 1

    @pytest.mark.parametrize("vite_dev_mode", [True, False])
    def test_every_declared_icon_exists_in_public_dir(self, vite_dev_mode):
        for _rel, _sizes, filename in _icon_specs(vite_dev_mode):
            assert (PUBLIC_DIR / filename).is_file(), f"missing {filename}"

    @pytest.mark.parametrize("vite_dev_mode", [True, False])
    def test_declared_sizes_match_actual_pixel_dimensions(self, vite_dev_mode):
        # Branch parity alone would not catch a `sizes` attribute that is
        # wrong in *both* branches (e.g. favicon-16.png declared 48x48).
        for _rel, sizes, filename in _icon_specs(vite_dev_mode):
            # "any" is legal on SVG icon links and would make the int() below
            # raise a bare ValueError; assert first so the failure names itself.
            assert re.fullmatch(r"\d+x\d+", sizes), f"unparseable sizes={sizes!r}"
            declared = tuple(int(n) for n in sizes.split("x"))
            assert _png_dimensions(PUBLIC_DIR / filename) == declared, (
                f"{filename} declares sizes={sizes} but its IHDR disagrees"
            )

    def test_dev_hrefs_are_absolute_vite_urls(self):
        # Root-relative hrefs would 404 when the document is served from
        # Django's :8006 origin directly (a working dev path, since the
        # module-script tags are absolute). Keep icons on the same
        # convention as those tags.
        for _rel, _sizes, href in _icon_links(vite_dev_mode=True):
            assert href.startswith(DEV_ORIGIN)
            # Vite serves publicDir at the origin root, so the remainder
            # must be a bare filename: http://localhost:5173/static/x.png
            # would satisfy a prefix check yet 404 in the browser.
            assert "/" not in href.removeprefix(DEV_ORIGIN)

    def test_prod_hrefs_are_root_absolute_static_urls(self):
        # Django normalises STATIC_URL to "/static/" via _add_script_prefix,
        # so these must not render path-relative (which would resolve
        # against nested routes like /accounts/login/).
        for _rel, _sizes, href in _icon_links(vite_dev_mode=False):
            assert href.startswith("/")
            assert href.startswith(settings.STATIC_URL)
            # public/ lands in the dist root, hence the static root — the
            # icons are never under a subdirectory like assets/.
            assert "/" not in href.removeprefix(settings.STATIC_URL)
