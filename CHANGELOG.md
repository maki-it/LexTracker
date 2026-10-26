# Changelog

## [0.9.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.8.0...lextracker-v0.9.0) (2026-10-26)


### Features

* **billing:** show the number of overdue invoices in the sidebar ([#184](https://github.com/maki-it/LexTracker/issues/184)) ([d65c763](https://github.com/maki-it/LexTracker/commit/d65c763ec43a67f6f0ad9c57b80d17b7f46a3997))


### Bug Fixes

* **lexware:** do not lose webhook calls when a sync fails unexpectedly ([#181](https://github.com/maki-it/LexTracker/issues/181)) ([1c6cf1f](https://github.com/maki-it/LexTracker/commit/1c6cf1fee5813ed182fbca8b5eef3b0c6b2ef735))

## [0.8.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.7.0...lextracker-v0.8.0) (2026-10-26)


### Features

* **lexware:** update only the changed customer or invoice on a webhook ([#180](https://github.com/maki-it/LexTracker/issues/180)) ([cb1d29f](https://github.com/maki-it/LexTracker/commit/cb1d29f1acffda75623f5db27e2ec65b3ee5310e))


### Bug Fixes

* **customers:** keep notes local when Lexware does not let the API change the contact ([#178](https://github.com/maki-it/LexTracker/issues/178)) ([fde8657](https://github.com/maki-it/LexTracker/commit/fde865742e7998554b820fcaa98e7dabf134d041))

## [0.7.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.6.0...lextracker-v0.7.0) (2026-10-26)


### Features

* **settings:** show the app version and repository link on an info tab ([#177](https://github.com/maki-it/LexTracker/issues/177)) ([72f01a1](https://github.com/maki-it/LexTracker/commit/72f01a1628c9ad08a6467940ed285e069e2dee97))


### Bug Fixes

* **lexware:** show a rejected API key as invalid instead of connected ([#175](https://github.com/maki-it/LexTracker/issues/175)) ([2d43380](https://github.com/maki-it/LexTracker/commit/2d4338033a1b21d26e9a585a422e050be2b26e91))

## [0.6.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.5.0...lextracker-v0.6.0) (2026-10-26)


### Features

* **lexware:** sync customers and invoices on Lexware webhooks ([#172](https://github.com/maki-it/LexTracker/issues/172)) ([a60bb69](https://github.com/maki-it/LexTracker/commit/a60bb690cf56210a4f4844f744ae135b65ab0fa9))
* **reminders:** filter reminders by status, customer and project; refresh the bell on its own ([#170](https://github.com/maki-it/LexTracker/issues/170)) ([fdb3cb0](https://github.com/maki-it/LexTracker/commit/fdb3cb062aca704fe2c6d8baef2c50806f17c432))
* **reminders:** remind about customers and projects, sync customer notes with Lexware ([#168](https://github.com/maki-it/LexTracker/issues/168)) ([687093f](https://github.com/maki-it/LexTracker/commit/687093fadf4743752ef35e9536f37afd4a94cf04))


### Bug Fixes

* **reminders:** align the due count in the sidebar with the other counts ([#171](https://github.com/maki-it/LexTracker/issues/171)) ([baeb5e5](https://github.com/maki-it/LexTracker/commit/baeb5e538f42e9c57674ed473cdf602129ba6fcf))
* **settings:** move the app address to the general settings and make the mail hint visible ([#173](https://github.com/maki-it/LexTracker/issues/173)) ([186df4c](https://github.com/maki-it/LexTracker/commit/186df4ce1f270e27f0f0397eda34c885f31c6945))

## [0.5.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.4.0...lextracker-v0.5.0) (2026-10-26)


### Features

* **branding:** configure app name and logo on the settings page ([#166](https://github.com/maki-it/LexTracker/issues/166)) ([e8ec19a](https://github.com/maki-it/LexTracker/commit/e8ec19a3d5012a123a562737f25187f81c9a14b1))

## [0.4.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.3.0...lextracker-v0.4.0) (2026-10-26)


### Features

* **docker:** add dev.compose.yaml for local development with watch ([#153](https://github.com/maki-it/LexTracker/issues/153)) ([1e29572](https://github.com/maki-it/LexTracker/commit/1e29572729ec934ade3421c08bb44db294399239))
* **i18n:** offer the interface in English next to German ([#159](https://github.com/maki-it/LexTracker/issues/159)) ([58edf6b](https://github.com/maki-it/LexTracker/commit/58edf6b8d61c6da5827171fb8e5f860d29b5d01d))
* **inbox:** show only unread messages by default ([#157](https://github.com/maki-it/LexTracker/issues/157)) ([60b75c4](https://github.com/maki-it/LexTracker/commit/60b75c4234ad1d4349ef3b8330f780a8f33d9426))
* **loadtest:** add make loadtest-ui to start the Locust web UI ([#158](https://github.com/maki-it/LexTracker/issues/158)) ([1a607c1](https://github.com/maki-it/LexTracker/commit/1a607c1ffb8b5fee075c6d1321f5f6961aadcfbd))
* **portal:** rename the "Zeiten" page to "Aufgaben" ([#160](https://github.com/maki-it/LexTracker/issues/160)) ([c38375c](https://github.com/maki-it/LexTracker/commit/c38375ce7de3107a06d1d6c0498e6b5a8564f21a))
* **setup:** ask for last name and require two-factor login for the first admin ([#155](https://github.com/maki-it/LexTracker/issues/155)) ([e977774](https://github.com/maki-it/LexTracker/commit/e97777432be87a5a42cc40c85813217d1206faa0))
* use English URL paths and query parameters ([#156](https://github.com/maki-it/LexTracker/issues/156)) ([3d9c823](https://github.com/maki-it/LexTracker/commit/3d9c8231fe598074639de4352bdd8c76230f13f3))


### Dependencies

* **project:** update project dependencies ([#137](https://github.com/maki-it/LexTracker/issues/137)) ([e90cb3d](https://github.com/maki-it/LexTracker/commit/e90cb3d195bbc2d4e0471fa8385098aabb967ef8))

## [0.3.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.2.0...lextracker-v0.3.0) (2026-10-25)


### Bug Fixes

* **ci:** read the image version from release-please's component tag ([#149](https://github.com/maki-it/LexTracker/issues/149)) ([cc02df7](https://github.com/maki-it/LexTracker/commit/cc02df712bf4dc46cc2dde2c9f7af1945293176d))


### Dependencies

* **python:** upgrade to Python 3.15 ([#152](https://github.com/maki-it/LexTracker/issues/152)) ([2bbc342](https://github.com/maki-it/LexTracker/commit/2bbc342a976c54d031d5d2e7ef4e997af0f95315))


### Miscellaneous

* release 0.3.0 ([c54df7c](https://github.com/maki-it/LexTracker/commit/c54df7c41d610c1c492a912cff51a252aa11b673))

## [0.2.0](https://github.com/maki-it/LexTracker/compare/lextracker-v0.1.0...lextracker-v0.2.0) (2026-10-24)


### ⚠ BREAKING CHANGES

* the previous application has been removed; it lives on the `old` branch.

### Features

* **account:** group account settings into tabs ([#147](https://github.com/maki-it/LexTracker/issues/147)) ([058f080](https://github.com/maki-it/LexTracker/commit/058f080ceb50138014369783995e19b8ea03814e))
* **accounts:** descriptions of time entries depend on seeing the entries ([#91](https://github.com/maki-it/LexTracker/issues/91)) ([4d6d2f4](https://github.com/maki-it/LexTracker/commit/4d6d2f44c0f8e2e2696cf58883d3b16b7df1ca27))
* **accounts:** employee and customer logins with a read-only customer portal ([#85](https://github.com/maki-it/LexTracker/issues/85)) ([d61d1bc](https://github.com/maki-it/LexTracker/commit/d61d1bc233450779baefb98830b81adb4a18ad40))
* **accounts:** show ready-to-copy MCP client setups on the account page ([#107](https://github.com/maki-it/LexTracker/issues/107)) ([e628425](https://github.com/maki-it/LexTracker/commit/e6284253fe9bb0e5eac0a09c1711230e94fdda71))
* add admin link to sidebar ([43896d2](https://github.com/maki-it/LexTracker/commit/43896d277796d1667dd1b3d0afc3f26941f8aefc))
* add class attribute to SVG for size specification ([77cf01e](https://github.com/maki-it/LexTracker/commit/77cf01e4595deeb3018b5507fd78a313f276a770))
* add Docker image ([#26](https://github.com/maki-it/LexTracker/issues/26)) ([53fbbb6](https://github.com/maki-it/LexTracker/commit/53fbbb67c413d3d08eeeee465a49e06add904713))
* add login page ([#29](https://github.com/maki-it/LexTracker/issues/29)) ([fd74591](https://github.com/maki-it/LexTracker/commit/fd745911880b7df088f44444d224ecc42621334a))
* add multiple SVG icons and chart rendering functions ([3012b47](https://github.com/maki-it/LexTracker/commit/3012b47c59dd785767a2d96a3418f078d22f2b2e))
* add new SVG icons and update calendar.js for accessibility ([506cf12](https://github.com/maki-it/LexTracker/commit/506cf127c4c696d8894c79c6668ec9c7d37aeafb))
* add toggle functionality for archived customers and projects ([#30](https://github.com/maki-it/LexTracker/issues/30)) ([ec23990](https://github.com/maki-it/LexTracker/commit/ec239903908375bff1372395ec3ea7ccb264131a))
* **billing:** bill time by hourly rate or retainer and create Lexware invoice drafts ([#76](https://github.com/maki-it/LexTracker/issues/76)) ([732d4d9](https://github.com/maki-it/LexTracker/commit/732d4d981b92f7a83d2d552a1dd632a35120d1fc))
* **billing:** label deleted invoice drafts and move the time hint into the status cell ([#132](https://github.com/maki-it/LexTracker/issues/132)) ([7979ded](https://github.com/maki-it/LexTracker/commit/7979ded043bbcadde679297e2b07f0584a923b90))
* **billing:** link the invoice number to Lexware instead of a separate link ([#127](https://github.com/maki-it/LexTracker/issues/127)) ([48a0256](https://github.com/maki-it/LexTracker/commit/48a02568947c76bcd0eb8aad67b5638bbc94c9f2))
* **billing:** list deleted drafts under the draft filter as well ([#135](https://github.com/maki-it/LexTracker/issues/135)) ([0f76b07](https://github.com/maki-it/LexTracker/commit/0f76b07d2281a9da02bd0472bb35acbaa83a7ce8))
* **billing:** mark invoices from Lexware with a small label instead of an icon ([#131](https://github.com/maki-it/LexTracker/issues/131)) ([6762084](https://github.com/maki-it/LexTracker/commit/6762084da3fb6a2fbc5d0db9045942b823787ce8))
* **billing:** mark periods with open time, bill any range, expandable preview lines ([#84](https://github.com/maki-it/LexTracker/issues/84)) ([67ea720](https://github.com/maki-it/LexTracker/commit/67ea720745b8a148ceac89b485e6f31a413a08b2))
* **billing:** name invoice lines after the task and describe project and period ([#133](https://github.com/maki-it/LexTracker/issues/133)) ([844adc2](https://github.com/maki-it/LexTracker/commit/844adc2e67e5e6193e4e2a853d3a0c1d12ebc824))
* **billing:** show invoice status as badge with due date below ([#130](https://github.com/maki-it/LexTracker/issues/130)) ([e7fafe0](https://github.com/maki-it/LexTracker/commit/e7fafe0fdcaf163aecc5bb4c620fa14ab3a3b84c))
* **billing:** show the open time entries of a customer in a dialog ([#128](https://github.com/maki-it/LexTracker/issues/128)) ([cc5a1d7](https://github.com/maki-it/LexTracker/commit/cc5a1d760ec8a96da75c56ca38dae5dca53566a3))
* **core:** show the scheduler's jobs and whether it is alive ([#141](https://github.com/maki-it/LexTracker/issues/141)) ([49c6a52](https://github.com/maki-it/LexTracker/commit/49c6a52c5a6388a2db77fc8401e562686d5d725f))
* **core:** upload a backup file from another server on the backups page ([#110](https://github.com/maki-it/LexTracker/issues/110)) ([f1c5029](https://github.com/maki-it/LexTracker/commit/f1c502947cf9b269d8fe94276cbcefe398e6919e))
* customer editing with Lexware write-back, automatic import, app and account settings with 2FA ([#77](https://github.com/maki-it/LexTracker/issues/77)) ([b594a6d](https://github.com/maki-it/LexTracker/commit/b594a6d6dd15556cca8726e1bd459f89daa4e17d))
* **customers:** import customers from Lexware Office ([#74](https://github.com/maki-it/LexTracker/issues/74)) ([ef20223](https://github.com/maki-it/LexTracker/commit/ef20223af5b7a48e460ea3c7f27b8bd21fae5b28))
* display username in the navbar ([2442c3b](https://github.com/maki-it/LexTracker/commit/2442c3b091a0c84964c8a9eecfc63e8b955a6d31))
* **docker:** harden compose setup and back up the database daily ([#93](https://github.com/maki-it/LexTracker/issues/93)) ([6cf1e88](https://github.com/maki-it/LexTracker/commit/6cf1e880994394ce6cd8ed126fec29d376084bde))
* employee booking unlocks and portal invoice filters ([#95](https://github.com/maki-it/LexTracker/issues/95)) ([13f0a52](https://github.com/maki-it/LexTracker/commit/13f0a523a9a2e0bedefd7118821aa6c21d8e103e))
* **inbox:** send users messages with priorities ([#140](https://github.com/maki-it/LexTracker/issues/140)) ([e07e8c2](https://github.com/maki-it/LexTracker/commit/e07e8c215d555b0ff5dba16bb5a9fb4eeb468fcb))
* **invoice:** add invoice generation ([#37](https://github.com/maki-it/LexTracker/issues/37)) ([bcd16ff](https://github.com/maki-it/LexTracker/commit/bcd16ff62c60602786c8103d2258e6b4ffc50b65))
* Lexware invoices and PDF download in the portal, account dialog, steady sidebar ([#94](https://github.com/maki-it/LexTracker/issues/94)) ([6027a9c](https://github.com/maki-it/LexTracker/commit/6027a9c344fb1e9423069e16304c578f3d7e95b5))
* **mailer:** e-mail overdue invoice notices and invitations ([#111](https://github.com/maki-it/LexTracker/issues/111)) ([e0b5db6](https://github.com/maki-it/LexTracker/commit/e0b5db658b4247dc315cb699d26942401c8cc95d))
* make customer numbers clickable links to their details ([6f8c8d0](https://github.com/maki-it/LexTracker/commit/6f8c8d0d2f0bef87b9bd6f627ce372076dc0e028))
* make project, category and customer tables sortable ([#31](https://github.com/maki-it/LexTracker/issues/31)) ([55fa3ce](https://github.com/maki-it/LexTracker/commit/55fa3ce34582034c8725189ead16a790dd36f55b))
* **mcp:** MCP server so AI agents can track time ([#83](https://github.com/maki-it/LexTracker/issues/83)) ([ce80727](https://github.com/maki-it/LexTracker/commit/ce807272ca2093f40aa2efca7406baaaf91a70ba))
* **portal:** address invoices by their number and link it to the PDF ([#125](https://github.com/maki-it/LexTracker/issues/125)) ([ad49e70](https://github.com/maki-it/LexTracker/commit/ad49e704f02dd332b2e94f7da0b522fb744c1871))
* **portal:** edit the contact person and show the customer number ([#118](https://github.com/maki-it/LexTracker/issues/118)) ([64e0945](https://github.com/maki-it/LexTracker/commit/64e09457d214eea325523ac6a1c961c83709d026))
* **portal:** let customers change their own contact in Lexware ([#113](https://github.com/maki-it/LexTracker/issues/113)) ([1f0b9f6](https://github.com/maki-it/LexTracker/commit/1f0b9f66faff30bc295accd342d37a171d77231c))
* **portal:** link time entries and invoices both ways ([#124](https://github.com/maki-it/LexTracker/issues/124)) ([3098007](https://github.com/maki-it/LexTracker/commit/3098007e0f5b641a42bdd4fd55218f7b43d925f9))
* **portal:** show the customer number as its own tile on the contact page ([#120](https://github.com/maki-it/LexTracker/issues/120)) ([b616565](https://github.com/maki-it/LexTracker/commit/b6165659f64b3a7403eafe26093af12a71626e93))
* **projects:** reusable task templates ([#99](https://github.com/maki-it/LexTracker/issues/99)) ([ea0f662](https://github.com/maki-it/LexTracker/commit/ea0f66287497ccfbd362b971b7c8c05f9881cc46))
* rebuild LexTracker from scratch (async Django, SQLite, htmx) ([#73](https://github.com/maki-it/LexTracker/issues/73)) ([f28dec4](https://github.com/maki-it/LexTracker/commit/f28dec466db4d9886d6bc8407bd8581ddf92a949))
* render Markdown in customer notes and project and task descriptions ([#104](https://github.com/maki-it/LexTracker/issues/104)) ([00dddc2](https://github.com/maki-it/LexTracker/commit/00dddc2644c40f8dbd30e53f4d858f15df65062e))
* **reports:** reports page with hours, revenue, budgets, retainers and CSV export ([#82](https://github.com/maki-it/LexTracker/issues/82)) ([0d0afda](https://github.com/maki-it/LexTracker/commit/0d0afda69dfdb4f8c5a974fcd45bdabb176d8b4d))
* search, categories, task editing, time rounding, invoice status and invoice list ([#79](https://github.com/maki-it/LexTracker/issues/79)) ([82b9410](https://github.com/maki-it/LexTracker/commit/82b9410b1ee28703be8de5a3d2ce88a74eb3d78e))
* select several status filters at once for invoices and projects ([#134](https://github.com/maki-it/LexTracker/issues/134)) ([9ae36cb](https://github.com/maki-it/LexTracker/commit/9ae36cbc82a2a6cb8aa5e4d39f21d3fdd2ecc5ac))
* send e-mails for password reset, login links, weekly reports and timer reminders ([#105](https://github.com/maki-it/LexTracker/issues/105)) ([de32f1a](https://github.com/maki-it/LexTracker/commit/de32f1a244902d1267458a14ed46851c47df8438))
* set the Lexware API key in the app and guide fresh instances through setup ([#102](https://github.com/maki-it/LexTracker/issues/102)) ([132dcd9](https://github.com/maki-it/LexTracker/commit/132dcd9e83beb67281b23d9892f2ce6e69bf9670))
* **settings:** configure database backups on the settings page ([#101](https://github.com/maki-it/LexTracker/issues/101)) ([69db371](https://github.com/maki-it/LexTracker/commit/69db3712c00ac09895f265f9c26cafb9ad9f3051))
* **settings:** highlight backup management in the backup tab ([#119](https://github.com/maki-it/LexTracker/issues/119)) ([266e4f0](https://github.com/maki-it/LexTracker/commit/266e4f0153c6150518d3758fa4b4769b6e1d5793))
* **settings:** manage and restore database backups in the app ([#103](https://github.com/maki-it/LexTracker/issues/103)) ([e2f9c18](https://github.com/maki-it/LexTracker/commit/e2f9c182d45895e7ae1ebe1ac5ebe5a5ee2f5f52))
* **settings:** separate schedule with time window for customer import and invoice sync ([#80](https://github.com/maki-it/LexTracker/issues/80)) ([340f660](https://github.com/maki-it/LexTracker/commit/340f66081c410ce68db1ce479a24294e2a01c79a))
* **settings:** split settings page into tabs ([#116](https://github.com/maki-it/LexTracker/issues/116)) ([2ef3fb9](https://github.com/maki-it/LexTracker/commit/2ef3fb95fc1301388fefb8a8b2d6b0745c5f4ab2))
* **setup:** add an optional e-mail step to the setup wizard ([#108](https://github.com/maki-it/LexTracker/issues/108)) ([65465fc](https://github.com/maki-it/LexTracker/commit/65465fc16e9026b3c48c091f27f64ca1b345e5d4))
* **tracking:** add a "Jetzt" button next to the start and end of an entry ([#123](https://github.com/maki-it/LexTracker/issues/123)) ([be1d91d](https://github.com/maki-it/LexTracker/commit/be1d91d6c1fe2336b6a94710896b004742a78e14))
* **tracking:** manage projects and track time ([#75](https://github.com/maki-it/LexTracker/issues/75)) ([e5c138a](https://github.com/maki-it/LexTracker/commit/e5c138a154e843c13f9f239730a6ecb135954a14))
* **tracking:** pick the task with a server-side search instead of a long list ([#112](https://github.com/maki-it/LexTracker/issues/112)) ([ea1ec5e](https://github.com/maki-it/LexTracker/commit/ea1ec5e1045ffcefabe400929dc8d489810954eb))
* **tracking:** round start and end of time entries to the nearest step ([#106](https://github.com/maki-it/LexTracker/issues/106)) ([4950297](https://github.com/maki-it/LexTracker/commit/49502971c11b9d0bcfdcba147fe1084516aa5723))
* **ui:** edit in dialogs, timer start from the sidebar, entry filters, project deletion, clearer archive ([#81](https://github.com/maki-it/LexTracker/issues/81)) ([708b471](https://github.com/maki-it/LexTracker/commit/708b471622eeb6e0373d3e5c3de24cc31c4a5828))
* **ui:** logo, favicon and a compact top bar on phones ([#87](https://github.com/maki-it/LexTracker/issues/87)) ([b9f61ca](https://github.com/maki-it/LexTracker/commit/b9f61cabf15bbd4da52786825a750b3c1a70a2a6))
* **ui:** redesign the app in a calm, Linear-like style ([#78](https://github.com/maki-it/LexTracker/issues/78)) ([51a7b09](https://github.com/maki-it/LexTracker/commit/51a7b09ae97ac44552f1b58f48b0b696c2189c1d))
* use UUIDs (v7) as primary keys everywhere ([#129](https://github.com/maki-it/LexTracker/issues/129)) ([013228d](https://github.com/maki-it/LexTracker/commit/013228d17d7aeebf9cdb6cb0697f11a374de251b))
* **users:** delete users and select all customers or projects at once ([#97](https://github.com/maki-it/LexTracker/issues/97)) ([359c0c6](https://github.com/maki-it/LexTracker/commit/359c0c62a28b249d45e0a10ec057e2d977568f88))
* **users:** search the booking lists and the customer select ([#117](https://github.com/maki-it/LexTracker/issues/117)) ([89d236b](https://github.com/maki-it/LexTracker/commit/89d236b2a8ef445e0701be9c3e590aac865a36f8))
* **users:** show the customer select as a searchable single-choice list ([#121](https://github.com/maki-it/LexTracker/issues/121)) ([101e7c0](https://github.com/maki-it/LexTracker/commit/101e7c06e2355cd6cfb5e658518fb8ced83257f7))


### Bug Fixes

* **accounts:** keep the descriptions choice while time entries are hidden ([#92](https://github.com/maki-it/LexTracker/issues/92)) ([ee6c287](https://github.com/maki-it/LexTracker/commit/ee6c28757700a08921ef6eb6c6f1f882dde3f4b2))
* add file watching and syncing to docker compose  ([#28](https://github.com/maki-it/LexTracker/issues/28)) ([1704dc5](https://github.com/maki-it/LexTracker/commit/1704dc57572a3f95f2d2d46e30a1d38979e608d9))
* add graceful shutdown timeout to uvicorn command ([f0018ba](https://github.com/maki-it/LexTracker/commit/f0018bab52185b4519bb955f443661403e282e0a))
* add peer dependencies to package-lock.json ([f223423](https://github.com/maki-it/LexTracker/commit/f2234239462c175339671521601172d222e8feaf))
* align arrow buttons with input ([3eb8a68](https://github.com/maki-it/LexTracker/commit/3eb8a688a0ca83de73c7487b3b17bc03795da659))
* **billing:** show a single service date instead of a one-day period ([#100](https://github.com/maki-it/LexTracker/issues/100)) ([811980a](https://github.com/maki-it/LexTracker/commit/811980af3162f024a8f4bb9656d1780310d2a70f))
* **customers:** refresh filter counts on import and reload after automatic imports ([#89](https://github.com/maki-it/LexTracker/issues/89)) ([6ef8fe5](https://github.com/maki-it/LexTracker/commit/6ef8fe55e941efb2ccbc29b67869883d4b1319df))
* **deps:** update all patch dependencies ([#23](https://github.com/maki-it/LexTracker/issues/23)) ([d239154](https://github.com/maki-it/LexTracker/commit/d239154b858a4d1d4df7a64bc3df516f8928dc18))
* **deps:** update dependency django-debug-toolbar to v6 ([#20](https://github.com/maki-it/LexTracker/issues/20)) ([909257e](https://github.com/maki-it/LexTracker/commit/909257e2712d7f2c81373c868b5c061e233835fa))
* duplicate action was not handled correctly ([e929651](https://github.com/maki-it/LexTracker/commit/e92965176fe765b5c15d2ce3123994dc250ed0d4))
* entry for current day was missing in reports table ([6a20b06](https://github.com/maki-it/LexTracker/commit/6a20b06dbe9d2f0e791ec2f28190377cc2c9f3bb))
* filter activities to exclude projects without customers ([50015ea](https://github.com/maki-it/LexTracker/commit/50015ea640aff3664c4a4bc99b51c0d24183c3de))
* implement pagination for reports activities table and update related templates ([#27](https://github.com/maki-it/LexTracker/issues/27)) ([f34b609](https://github.com/maki-it/LexTracker/commit/f34b60974fceaade992af48f74cf2c982c17c5e1))
* **mailer:** explain mismatched SMTP port and encryption ([#139](https://github.com/maki-it/LexTracker/issues/139)) ([dff2ca0](https://github.com/maki-it/LexTracker/commit/dff2ca08c627a3f2f0c57a8676f4d1af5c17a48e))
* remove space ([08ea719](https://github.com/maki-it/LexTracker/commit/08ea7190de589b369a5e6b27619921164cc06fc1))
* **tracking:** bring back the native time picker and snap times to the step ([#115](https://github.com/maki-it/LexTracker/issues/115)) ([58207a7](https://github.com/maki-it/LexTracker/commit/58207a7c820549cdf6290ed1ee68b2bf6e1392a0))
* **tracking:** let minutes be typed freely and snap to the step on blur ([#126](https://github.com/maki-it/LexTracker/issues/126)) ([fbbcc69](https://github.com/maki-it/LexTracker/commit/fbbcc69cf6d2a3f2c316213e3cebbf27986d51d2))
* **tracking:** offer only times on the rounding step when booking ([#109](https://github.com/maki-it/LexTracker/issues/109)) ([a88b235](https://github.com/maki-it/LexTracker/commit/a88b235b776cee389cb6b4673066fe11f5ad90f7))
* **ui:** resolve the favicon redirect per request ([#90](https://github.com/maki-it/LexTracker/issues/90)) ([35e3588](https://github.com/maki-it/LexTracker/commit/35e35884e4a07088742e42f949289b4f5123df06))
* update API endpoint from lexoffice to lexware ([b3e16a5](https://github.com/maki-it/LexTracker/commit/b3e16a5c0a26b286abef54d0456ed87f085d2a4c))
* update daisyui package version to 4.12.24 ([8787414](https://github.com/maki-it/LexTracker/commit/8787414e06232df5c195c158d3e2ddbea43be229))
* update httpx-limiter to use aiolimiter and adjust dependencies ([0108dcb](https://github.com/maki-it/LexTracker/commit/0108dcb19c9619eba7141656d7e437a60235a2e9))
* update Makefile to use correct syntax for activating virtual environment ([686bcb4](https://github.com/maki-it/LexTracker/commit/686bcb41dc5626b6fdf408e21dce5c2de23362e3))
* **users:** scroll the customer list to the chosen customer ([#122](https://github.com/maki-it/LexTracker/issues/122)) ([069580d](https://github.com/maki-it/LexTracker/commit/069580d4c79ec19389679eb385b66819309df397))


### Performance

* **docker:** improve build caching ([#114](https://github.com/maki-it/LexTracker/issues/114)) ([5e7f2c0](https://github.com/maki-it/LexTracker/commit/5e7f2c0d35d05c5684bb8e80112711c16dc906d1))
* lighter task picker, SQL reports, paged lists, login rate limit and compression ([#98](https://github.com/maki-it/LexTracker/issues/98)) ([164b03d](https://github.com/maki-it/LexTracker/commit/164b03de7bf069baa4507ed998b119db084f4400))


### Dependencies

* **project:** lock file maintenance ([#42](https://github.com/maki-it/LexTracker/issues/42)) ([7926928](https://github.com/maki-it/LexTracker/commit/792692880c995dcd1d610f0e0da987e2d1a66691))
* **project:** lock file maintenance project dependencies ([#36](https://github.com/maki-it/LexTracker/issues/36)) ([580a2e4](https://github.com/maki-it/LexTracker/commit/580a2e42d654b4bab54abea938b45b5bf6796d23))
* **project:** update dependency cryptography to v46 ([#145](https://github.com/maki-it/LexTracker/issues/145)) ([7a1d4ec](https://github.com/maki-it/LexTracker/commit/7a1d4ecb9a70f035e14e6182bee70f9e2e1f3d39))
* **project:** update dependency django to v6.0.2 [security] ([#39](https://github.com/maki-it/LexTracker/issues/39)) ([60f4f1b](https://github.com/maki-it/LexTracker/commit/60f4f1b6bfb0b6d06956c558bf09b0e3e50453db))
* **project:** update dependency django to v6.0.3 [security] ([#43](https://github.com/maki-it/LexTracker/issues/43)) ([db0ac80](https://github.com/maki-it/LexTracker/commit/db0ac8027c35b236cd2e9917869c94f3d85f9387))
* **project:** update dependency django to v6.0.4 [security] ([#54](https://github.com/maki-it/LexTracker/issues/54)) ([18a27ad](https://github.com/maki-it/LexTracker/commit/18a27ad77cec9bca23982fd30c5b949a6b770b2d))
* **project:** update dependency django to v6.0.5 [security] ([#59](https://github.com/maki-it/LexTracker/issues/59)) ([2510444](https://github.com/maki-it/LexTracker/commit/2510444f7ed1b318b404837bc272c85f9c9f3946))
* **project:** update dependency django to v6.0.6 [security] ([#66](https://github.com/maki-it/LexTracker/issues/66)) ([881369c](https://github.com/maki-it/LexTracker/commit/881369c1fd469802b2b46d49d5d09630f677be86))
* **project:** update httpx-limiter digest to 69aba6f ([#50](https://github.com/maki-it/LexTracker/issues/50)) ([cb7b9db](https://github.com/maki-it/LexTracker/commit/cb7b9db4448daae2c0f84f2c5eb33b87d828c710))
* **project:** update project dependencies ([#38](https://github.com/maki-it/LexTracker/issues/38)) ([61bbaba](https://github.com/maki-it/LexTracker/commit/61bbaba402904952753da27e15488db515cdec26))
* **project:** update project dependencies ([#45](https://github.com/maki-it/LexTracker/issues/45)) ([a40b16b](https://github.com/maki-it/LexTracker/commit/a40b16bc48d155334a584c3b2feb3967b86ecf6b))
