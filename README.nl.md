# Visual Resonance — Eindwerk

> **Luca Lattuca, Erasmushogeschool Brussel, 2025–2026**

---

## Wat is Visual Resonance?

Visual Resonance is een realtime audiovisuele installatie die een live muziekuitvoering omzet in generatieve beelden en abstracte motion graphics. Audio van meerdere instrumenten wordt gelijktijdig geanalyseerd — toonhoogte, tempo, timbre, harmonie, dynamiek, stemming en genre worden geëxtraheerd en gekoppeld aan visuele parameters in TouchDesigner en AI-gegenereerde beelden via Stable Diffusion.

Visual Resonance wil de auditieve dimensie van muziek uitbreiden door er een visuele laag aan toe te voegen die elk muzikaal element vertegenwoordigt. Door een realtime visualisatie-ervaring te creëren, fungeert het project als een verlengstuk van menselijke creativiteit en biedt het een dieper begrip van muziek.

Dit project is gebouwd als eindwerk voor de bachelor Multimedia en Creatieve Technologieën.

---

## MUSINFO

MUSINFO is de ondersteunende desktopapplicatie die voor Visual Resonance werd ontwikkeld. Het beheert de volledige audioanalysepipeline: instrumenten en audioapparaten configureren, en analysedata via OSC doorsturen naar TouchDesigner en het beeldgeneratiesysteem.

MUSINFO draait uitsluitend op **Windows**. macOS wordt niet ondersteund vanwege de WSL-gebaseerde analysepipeline.

---

### Technische Stack

| Laag | Technologie |
|---|---|
| Desktopapplicatie | Tauri 2 (Rust) |
| Gebruikersinterface | React 19 + Vite 7 |
| Windows audio-opname | Python 3.13 · sounddevice |
| MIDI-opname | Python 3.13 · pygame.midi |
| Windows-analysers | Python 3.13 · Aubio |
| WSL-analysers | Python 3.12 · Essentia-TensorFlow · librosa |
| GPU-inferentie | NVIDIA GPU · CUDA via WSL2 |
| Beeldgeneratie | SD Turbo (lokaal) |
| Visuele engine | TouchDesigner |
| Communicatie tussen processen | TCP-sockets · OSC (python-osc) |
| Videorouting | NDI |

---

### Functies

**Instrumentbeheer** — Voeg instrumenten toe, configureer, hernoem en verwijder ze. Wijs elk instrument een rol en rolindex toe die het OSC-adres in TouchDesigner bepalen.

**Audioapparaatondersteuning** — Ondersteunt ASIO, WASAPI en MME host-API's. MUSINFO werkt met vrijwel elke audio-interface of virtueel apparaat. De enige beperking is dat instrumenten met verschillende host-API's niet gecombineerd kunnen worden binnen één sessie — alle actieve instrumenten moeten dezelfde host-API gebruiken.

**MIDI-ondersteuning** — Koppel een MIDI-controller via loopMIDI. MIDI-harmonie wordt rechtstreeks uit nootgebeurtenissen geanalyseerd, zonder audio-opname.

**Pipeline-aansturing** — Start en stop de volledige pipeline met één klik. Alle achtergrondprocessen worden automatisch beheerd.

**OSC-configuratie** — Toont alle actieve OSC-adressen voor de huidige sessie, afgeleid van de instrumentconfiguratie. Gebruik dit voor het instellen van TouchDesigner-invoernodes.

**Sessiebeheer** — Sla sessies op en laad ze via het native OS-menu (Bestand → Sessie opslaan / Sessie laden).

**Uitvoeringstab** — Realtime pianotoetsenbordweergave met actieve MIDI-noten en gedetecteerde harmonie.

---

### Installatie

> ⚠️ MUSINFO is ontwikkeld en getest op Windows 11 met een NVIDIA GPU. Het draait niet op macOS zonder grondige aanpassingen aan de afhankelijkheden en architectuur.

---

#### Vereisten

- [Node.js](https://nodejs.org/) 18 of nieuwer
- [Rust](https://rustup.rs/) (stabiele toolchain)
- [Python 3.13](https://www.python.org/downloads/) (Windows)
- WSL2 met Ubuntu 24.04 LTS (Noble) — [installatiegids](https://learn.microsoft.com/en-us/windows/wsl/install)
- NVIDIA GPU met CUDA-ondersteuning (voor de genre-, stemming- en TempoCNN-analysers)
- [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) — voor MIDI-routing
- [TouchDesigner](https://derivative.ca/) (recente versie)
- [NDI Tools](https://ndi.video/tools/) — voor het doorsturen van gegenereerde beelden naar TouchDesigner

---

#### Windows Python-pakketten

```bash
pip install sounddevice python-osc numpy aubio pygame scipy
```

---

#### WSL — Python 3.12-installatie

Ubuntu 24.04 LTS (Noble) wordt standaard geleverd met Python 3.12. Er is geen aparte installatie nodig. Controleer de versie:

```bash
python3.12 --version
```

Maak een virtuele omgeving aan in de WSL-backendmap:

```bash
cd /mnt/c/<pad-naar-project>/musinfo/backend/wsl
python3.12 -m venv .venv
source .venv/bin/activate
```

Installeer de benodigde pakketten in de virtuele omgeving:

```bash
pip install essentia-tensorflow numpy scipy pythonosc librosa
```

> `essentia-tensorflow` installeert Essentia met TensorFlow-ondersteuning, vereist voor de genre-, stemming-, CREPE- en TempoCNN-modellen. Dit kan enkele minuten duren.

De WSL-ontvangstscripts activeren deze virtuele omgeving automatisch wanneer Tauri ze opstart.

---

#### Essentia-modellen

Alle ML-modellen moeten handmatig worden gedownload en in de juiste mappen worden geplaatst. Modelbestanden worden niet meegeleverd in de repository.

Essentia-modeldocumentatie: [essentia.upf.edu/models.html](https://essentia.upf.edu/models.html)  
Essentia-algoritmeverwijzing: [essentia.upf.edu/algorithms_reference.html](https://essentia.upf.edu/algorithms_reference.html)

Alle Essentia-modellen zijn gelicentieerd onder [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

---

**Discogs-EffNet** — gedeelde feature-extractor voor genre en stemming  
Plaatsen in: `musinfo/backend/wsl/models/`

| Bestand | Download |
|---|---|
| `discogs-effnet-bs64-1.pb` | [download](https://essentia.upf.edu/models/feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb) |
| `discogs-effnet-bs64-1.json` | [download](https://essentia.upf.edu/models/feature-extractors/discogs-effnet/discogs-effnet-bs64-1.json) |

---

**CREPE-toonhoogtemodellen** — neurale toonhoogtedetectie  
Plaatsen in: `musinfo/backend/wsl/models/pitch_models/`  
Beide groottes zijn inbegrepen; het actieve model wordt ingesteld via `MODEL_SIZE` in `pitch_crepe_analyser.py`.

| Bestand | Download |
|---|---|
| `crepe-medium-1.pb` | [download](https://essentia.upf.edu/models/pitch/crepe/crepe-medium-1.pb) |
| `crepe-medium-1.json` | [download](https://essentia.upf.edu/models/pitch/crepe/crepe-medium-1.json) |
| `crepe-large-1.pb` | [download](https://essentia.upf.edu/models/pitch/crepe/crepe-large-1.pb) |
| `crepe-large-1.json` | [download](https://essentia.upf.edu/models/pitch/crepe/crepe-large-1.json) |

---

**Stemming- en dansbaarheidsmodellen**  
Plaatsen in: `musinfo/backend/wsl/models/mood_models/`

| Bestand | Download |
|---|---|
| `mood_aggressive-discogs-effnet-1.pb` | [download](https://essentia.upf.edu/models/classification-heads/mood_aggressive/mood_aggressive-discogs-effnet-1.pb) |
| `mood_aggressive-discogs-effnet-1.json` | [download](https://essentia.upf.edu/models/classification-heads/mood_aggressive/mood_aggressive-discogs-effnet-1.json) |
| `mood_happy-discogs-effnet-1.pb` | [download](https://essentia.upf.edu/models/classification-heads/mood_happy/mood_happy-discogs-effnet-1.pb) |
| `mood_happy-discogs-effnet-1.json` | [download](https://essentia.upf.edu/models/classification-heads/mood_happy/mood_happy-discogs-effnet-1.json) |
| `mood_party-discogs-effnet-1.pb` | [download](https://essentia.upf.edu/models/classification-heads/mood_party/mood_party-discogs-effnet-1.pb) |
| `mood_party-discogs-effnet-1.json` | [download](https://essentia.upf.edu/models/classification-heads/mood_party/mood_party-discogs-effnet-1.json) |
| `mood_relaxed-discogs-effnet-1.pb` | [download](https://essentia.upf.edu/models/classification-heads/mood_relaxed/mood_relaxed-discogs-effnet-1.pb) |
| `mood_relaxed-discogs-effnet-1.json` | [download](https://essentia.upf.edu/models/classification-heads/mood_relaxed/mood_relaxed-discogs-effnet-1.json) |
| `mood_sad-discogs-effnet-1.pb` | [download](https://essentia.upf.edu/models/classification-heads/mood_sad/mood_sad-discogs-effnet-1.pb) |
| `mood_sad-discogs-effnet-1.json` | [download](https://essentia.upf.edu/models/classification-heads/mood_sad/mood_sad-discogs-effnet-1.json) |
| `danceability-discogs-effnet-1.pb` | [download](https://essentia.upf.edu/models/classification-heads/danceability/danceability-discogs-effnet-1.pb) |
| `danceability-discogs-effnet-1.json` | [download](https://essentia.upf.edu/models/classification-heads/danceability/danceability-discogs-effnet-1.json) |
| `mtg_jamendo_moodtheme-discogs-effnet-1.pb` | [download](https://essentia.upf.edu/models/classification-heads/mtg_jamendo_moodtheme/mtg_jamendo_moodtheme-discogs-effnet-1.pb) |
| `mtg_jamendo_moodtheme-discogs-effnet-1.json` | [download](https://essentia.upf.edu/models/classification-heads/mtg_jamendo_moodtheme/mtg_jamendo_moodtheme-discogs-effnet-1.json) |

---

**TempoCNN** — neurale BPM-schatting  
Plaatsen in: `musinfo/backend/wsl/models/bpm_models/`

| Bestand | Download |
|---|---|
| `deepsquare-k16-3.pb` | [download](https://essentia.upf.edu/models/tempo/tempocnn/deepsquare-k16-3.pb) |
| `deepsquare-k16-3.json` | [download](https://essentia.upf.edu/models/tempo/tempocnn/deepsquare-k16-3.json) |

---

#### Frontend

```bash
cd musinfo
npm install
npm run tauri dev
```

---

## Muziekvisualisatie

De visuele output van Visual Resonance bestaat uit twee lagen:

**TouchDesigner** ontvangt realtime OSC-data van de analysers en koppelt muzikale parameters aan visuele eigenschappen. Dynamiek wordt gekoppeld aan schaal, toonhoogte aan verticale positie, timbre aan vorm en textuur, harmonie aan kleur...

In TouchDesigner wordt een volledige OSC-mapping opgebouwd op basis van de analysers die in MUSINFO zijn ingebouwd. Het TouchDesigner-bestand bevindt zich op `touchdesigner/Harmonic_Visuals.toe`.

> **Git LFS vereist** — Het `.toe`-bestand wordt opgeslagen via Git Large File Storage. Om het werkelijke bestand op te halen na het klonen van de repository, installeer [Git LFS](https://git-lfs.com/) en voer `git lfs pull` uit. Zonder dit bevat de map `touchdesigner/` slechts een tekstverwijzing in plaats van het binaire patch-bestand.

**AI-beeldgeneratie** gebruikt een prompt samengesteld uit genre, stemming en harmonische context om beelden te genereren via SD Turbo. Deze worden via NDI naar TouchDesigner gestreamd en bij elke nieuwe generatie overgecrossfade.

---

## Architectuur & Onderhoud

Voor een volledig overzicht van de systeemarchitectuur — audiopipeline, analyser-internals, OSC-adresschema en beeldgeneratie — zie [ARCHITECTURE.nl.md](./ARCHITECTURE.nl.md).

Voor informatie over het onderhouden van de codebase, het toevoegen van analysers en bekende problemen, zie [MAINTENANCE.nl.md](./MAINTENANCE.nl.md).

---

## Gebruik van AI bij Ontwikkeling

AI is uitvoerig ingezet tijdens de ontwikkeling van MUSINFO. Voor transparantie zijn alle gesprekken die tijdens het ontwikkelproces zijn gebruikt opgenomen in de documentatie.

De volgende sectie bevat een overzicht van alle Claude-gesprekken (model Sonnet 4.6, voornamelijk gebruikt) voor het maken en debuggen van componenten, het bouwen van de audiopipeline, het ontwikkelen van audio-analysers, debuggen, refactoring en meer.

Ondanks het uitgebreide gebruik van Claude AI is er veel aandacht besteed aan het consistent houden van de architectuur en naamgevingsconventies. Omdat AI de neiging heeft om hallucinaties te produceren en slechte naamgevingsconventies toe te passen, is de complexiteit van de code aan de hogere kant. Documentatie en codecommentaar zijn consistent gehouden in alle bestanden met een uniforme structuur en taal.

### Add instrument Modal creation + component bug fixing

- https://claude.ai/share/5c050779-83c6-4c1e-ad70-885d1f4ed813

### refactoring react components architecture

- https://claude.ai/share/b3256154-9a6d-452c-b67a-93c605eae0f2

### pitch analyser using

- https://claude.ai/share/cb1d81fc-e826-4615-b196-d0cad89bcf4a

## research on genre classification using essentia and implementing real time into a genre classifier

- https://claude.ai/share/81bc0885-13c0-4478-b940-ba370920fdd4
- https://claude.ai/share/81bc0885-13c0-4478-b940-ba370920fdd4

### Audio device selection bug fixing + device feedback

- https://claude.ai/share/4e9a0a24-b157-4a37-a8d9-6d4b5abb6006

### Audio Pipeline fix and degugging + OSC throughput

- https://claude.ai/share/acec0893-8ae6-47f0-b5ad-70d1538fdb26
- https://claude.ai/share/6641ac3b-5534-43dd-b4e5-4753671aeaa0
- https://claude.ai/share/6641ac3b-5534-43dd-b4e5-4753671aeaa0

## Essentia Mood Analyser ins WSL

- https://claude.ai/share/d19e2d4a-0844-4664-9941-c98396c9a685

## Rust native OS menu

- https://claude.ai/share/a5a8b937-1181-41b0-b1fd-183bca72ffb6

## Debug audio implementation in broadcaster

- https://claude.ai/share/c5aceabb-907d-4f81-a70a-bef9c113bb65

## audio pipeline latency testing (not merged)

- https://claude.ai/share/751523bc-0515-4642-864a-9c98a185c989

## dynamics analyser : onset, amplitude and onset strength (determines energy for individuals instruments)

- https://claude.ai/share/564582dd-b1bd-4e47-ad32-bc4b22cf2c72

## bpm and tempo analyser + refactoring

- https://claude.ai/share/183bc878-646f-4263-9c4f-073b5b1a9d3e
- https://claude.ai/share/b1bf97bf-82ce-4f63-83d4-8a5d68cfe0ab

## pipeline latency test (not merged)

- https://claude.ai/share/751523bc-0515-4642-864a-9c98a185c989

## Timbre analysis development

- https://claude.ai/share/4ac1d46d-4048-4d5d-a927-e5d261ba3472

## harmonical analysis : audio

- https://claude.ai/share/77546995-40b5-4945-98b2-369e6bd750ff

## Touchdesigner fade effect and image generator tweaking

- https://claude.ai/share/37d83ce7-5d11-4eab-9030-664a81810d43

## Prompt to image generation and OSC throughput

- https://claude.ai/share/d923d23d-8a52-45e4-a000-eedc90586121

## Refactor Internal Mix to use Time based queue + audio debug fix

- https://claude.ai/share/c54338eb-5db0-4aff-9c80-28d9a5629a87

## mix instrument configuration

- https://claude.ai/share/72596e10-6b76-45c4-8286-4f7fe230afcb

## sending data to touchdesigner over OSC and update analysers adresses

- https://claude.ai/share/9ac99f6a-96a9-4556-8d71-e53b945c2165

## Hot reload for performance tab to harmony analyser and piano keyboard component

- https://claude.ai/share/57f251b3-7211-405d-a846-187438d2727b

## Midi_harmony_analyser and debugging forced key and hot reload

- https://claude.ai/share/5af04986-82b5-4222-8e87-25096c406d18

## React switch component

- https://claude.ai/share/8ed83b97-baf1-4956-9915-28b4958c5aec

## Mix instrument on last order

- https://claude.ai/share/ee11e5c3-f953-4e45-a1a1-2045fcc10b36

## Refactor instruments and pipeline optimization and debug image generation SDTURBO errors

- https://claude.ai/share/41b242fb-aaf6-466f-bb52-5d3ea1b65629
- https://claude.ai/share/75042211-a2db-4f8f-a0e1-ed2f74422302

## reducing audio lag upon swapping to setup tab

- https://claude.ai/share/998d52d7-a0d8-4f29-82fd-1d5120c93b3e

## Creating Readme, Arcitecture and Maintenance.md files

- https://claude.ai/share/964b9f8e-21ae-4da5-95d8-4ea373d6eb4f
