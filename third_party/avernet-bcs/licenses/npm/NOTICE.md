# Reviewed npm license metadata overrides

The two exact development packages below omit a `license` field from their npm
metadata and lockfile entry. Their release-tag source trees contain the MIT
license. The license-policy gate applies these records only to the exact
coordinate and verifies the adjacent license-text SHA-256; any version change
or content drift fails closed.

| Coordinate | npm integrity | Upstream Git revision | License source | License SHA-256 |
| --- | --- | --- | --- | --- |
| `egg-bin@6.13.0` | `sha512-dlztm1Y5DnSkofCeTaMf+O7kARPDGFbcbLDJ5cc029qRRbhStM7AsBBgLc+EEZuumZupejDHdvxraXRVut1ZTA==` | `f4774359e4158301b60d627acf05a4736423a6f3` | `https://github.com/eggjs/egg-bin/blob/v6.13.0/LICENSE` | `173f66e69918077fed894c20e05411601c31f9e249c3759671446d61fbdb92c7` |
| `eslint-config-egg@14.1.0` | `sha512-+B3IbYgT/cBfYhpBjMwUCK4GbdnJ6EsGBO8R9No5bd75bHgzRAp8nJ9jki6OOlaWGZkgycyAyTDvh5D7NPlGJg==` | `f60c9e0353073596b7c016a40e378bce4310262d` | `https://github.com/eggjs/eslint-config-egg/blob/v14.1.0/LICENSE` | `a1b75b6fe271c904a62cce7b996da61b3538e4060e3364a4ed43f56b28259d6f` |

These records restore omitted package metadata; they do not waive or broaden
the license policy.
