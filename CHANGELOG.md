# Changelog

## [0.6.1](https://github.com/chocs-cat/tack/compare/v0.6.0...v0.6.1) (2026-10-27)


### Bug Fixes

* **doctor:** report a hook file two harnesses list as unreadable once ([#87](https://github.com/chocs-cat/tack/issues/87)) ([8a9c5f7](https://github.com/chocs-cat/tack/commit/8a9c5f7e9a4d7600df07cc2ca77fc13deff0ed8a)), closes [#83](https://github.com/chocs-cat/tack/issues/83)

## [0.6.0](https://github.com/chocs-cat/tack/compare/v0.5.2...v0.6.0) (2026-10-26)


### Features

* **doctor:** report a plugin a project sets for one agent only ([#82](https://github.com/chocs-cat/tack/issues/82)) ([5aeaaef](https://github.com/chocs-cat/tack/commit/5aeaaef1067a1f5c6c9d530fd57a47f8a3516832)), closes [#24](https://github.com/chocs-cat/tack/issues/24)
* **doctor:** report skills a deployed plugin also carries ([#79](https://github.com/chocs-cat/tack/issues/79)) ([f269720](https://github.com/chocs-cat/tack/commit/f269720ece1a09ec74864f3784e86caa52c46947)), closes [#25](https://github.com/chocs-cat/tack/issues/25)

## [0.5.2](https://github.com/chocs-cat/tack/compare/v0.5.1...v0.5.2) (2026-10-20)


### Bug Fixes

* run the agents' CLIs in a session of their own ([#74](https://github.com/chocs-cat/tack/issues/74)) ([02701b5](https://github.com/chocs-cat/tack/commit/02701b5985b7934f7884839babe5a6d3441ab407)), closes [#72](https://github.com/chocs-cat/tack/issues/72)

## [0.5.1](https://github.com/chocs-cat/tack/compare/v0.5.0...v0.5.1) (2026-10-20)


### Bug Fixes

* **tui:** leave the skills line out of a plugin-only source's detail ([#70](https://github.com/chocs-cat/tack/issues/70)) ([5d0053d](https://github.com/chocs-cat/tack/commit/5d0053d7c045837d1ff855e6570eaccc56913aa3)), closes [#52](https://github.com/chocs-cat/tack/issues/52) [#60](https://github.com/chocs-cat/tack/issues/60)

## [0.5.0](https://github.com/chocs-cat/tack/compare/v0.4.0...v0.5.0) (2026-10-10)


### Features

* **skills:** ship instructions-setup ([#66](https://github.com/chocs-cat/tack/issues/66)) ([1e75a94](https://github.com/chocs-cat/tack/commit/1e75a94706ef9c73b3583e8dd16b15d1dc52761a))

## [0.4.0](https://github.com/chocs-cat/tack/compare/v0.3.0...v0.4.0) (2026-10-09)


### Features

* **cli:** `tack add --plugin` selects plugins (P0001-C08) ([#48](https://github.com/chocs-cat/tack/issues/48)) ([d51ff10](https://github.com/chocs-cat/tack/commit/d51ff10ff3d93bbeebe0ec53d73d001aa02ad7e3)), closes [#46](https://github.com/chocs-cat/tack/issues/46) [#47](https://github.com/chocs-cat/tack/issues/47)
* deploy plugins from other repositories (P0001-C11) ([#55](https://github.com/chocs-cat/tack/issues/55)) ([c954779](https://github.com/chocs-cat/tack/commit/c954779456a2c72890baaa026ccb6ce481d11a2b)), closes [#54](https://github.com/chocs-cat/tack/issues/54)
* doctor audits plugins (P0001-C06) ([#41](https://github.com/chocs-cat/tack/issues/41)) ([32ca329](https://github.com/chocs-cat/tack/commit/32ca329e0f44569b9d58e9670b7f8812b820a937))
* outdated tracks plugins (P0001-C07) ([#45](https://github.com/chocs-cat/tack/issues/45)) ([5998bac](https://github.com/chocs-cat/tack/commit/5998bac6c9eac51f29cd1e6ada3abdb58429def3)), closes [#44](https://github.com/chocs-cat/tack/issues/44)
* show and diff plugins from other repositories (P0001-C12) ([#58](https://github.com/chocs-cat/tack/issues/58)) ([1ed0853](https://github.com/chocs-cat/tack/commit/1ed0853458b4706f79e6882ca12b882367d87595))
* status shows plugin states (P0001-C05) ([#37](https://github.com/chocs-cat/tack/issues/37)) ([0b78ae1](https://github.com/chocs-cat/tack/commit/0b78ae13d8350adbb84239a786478d1bd04acf09)), closes [#35](https://github.com/chocs-cat/tack/issues/35)
* sync deploys plugins to Claude Code and Codex (P0001-C04) ([#34](https://github.com/chocs-cat/tack/issues/34)) ([5f4cd60](https://github.com/chocs-cat/tack/commit/5f4cd60b0d68ec80d3be92a4840538e00a8ea83d))
* **tui:** a Plugins tab (P0001-C09) ([#50](https://github.com/chocs-cat/tack/issues/50)) ([d0d10e6](https://github.com/chocs-cat/tack/commit/d0d10e63092c68c17f35f3a664522afc693d7b3f)), closes [#43](https://github.com/chocs-cat/tack/issues/43) [#49](https://github.com/chocs-cat/tack/issues/49)

## [0.3.0](https://github.com/chocs-cat/tack/compare/v0.2.0...v0.3.0) (2026-09-28)


### Features

* ship an agent skill for tack ([#19](https://github.com/chocs-cat/tack/issues/19)) ([615f7e6](https://github.com/chocs-cat/tack/commit/615f7e6c7b244c5b7048ea5b820c2b883794b273))
* **tui:** open on the Skills tab and stay there ([#18](https://github.com/chocs-cat/tack/issues/18)) ([ba1f298](https://github.com/chocs-cat/tack/commit/ba1f298eaa83e77c03c9c08f008b7331439686ea))

## [0.2.0](https://github.com/chocs-cat/tack/compare/v0.1.0...v0.2.0) (2026-09-28)


### Features

* **tui:** a Settings screen for the manifest ([#16](https://github.com/chocs-cat/tack/issues/16)) ([5d5a1c7](https://github.com/chocs-cat/tack/commit/5d5a1c70ceb1941cb37c14a4e4935b4dc8a3a063))
* **tui:** group the Skills table by source ([#15](https://github.com/chocs-cat/tack/issues/15)) ([5f3a09e](https://github.com/chocs-cat/tack/commit/5f3a09e46e2f8c0983eb4cfef335526fb6a0143b))
* **tui:** show the version and the manifest's path in the header ([#9](https://github.com/chocs-cat/tack/issues/9)) ([dac7bd0](https://github.com/chocs-cat/tack/commit/dac7bd05ceb32969e204d95c780c50662d2b5170))
* **tui:** sort the Skills table by any column ([#13](https://github.com/chocs-cat/tack/issues/13)) ([2f5cb52](https://github.com/chocs-cat/tack/commit/2f5cb5229df2e9bcca0a3e8859fbf1dbb5cd67be))


### Bug Fixes

* **tui:** keep the header one line when clicked ([#7](https://github.com/chocs-cat/tack/issues/7)) ([33b7d10](https://github.com/chocs-cat/tack/commit/33b7d1040def57578569f2da36f85fd987d5b89c))
* **tui:** stop late tab events from undoing the tab pick or swapping tabs ([#14](https://github.com/chocs-cat/tack/issues/14)) ([4964a11](https://github.com/chocs-cat/tack/commit/4964a1150ebe704cead455bd06fc7a6405389487))

## 0.1.0 (2026-09-27)


### Features

* install tack from PyPI or Homebrew ([33d716d](https://github.com/chocs-cat/tack/commit/33d716d7c3e4f45d9d4457de4c7e2ab31c0b40ad))
