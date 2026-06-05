# MUSINFO — Systeemarchitectuur

Dit document beschrijft de volledige architectuur van MUSINFO: van gebruikersinterface tot audio-opname, uitzending, analyse, OSC-routing en beeldgeneratie.

---

## Inhoudsopgave

1. [Overzicht](#overzicht)
2. [Gebruikersinterface — React + Tauri](#gebruikersinterface--react--tauri)
3. [Rust-backend — lib.rs + menu.rs](#rust-backend--librs--menurs)
4. [Audiopipeline](#audiopipeline)
5. [Analysers](#analysers)
6. [OSC-routing](#osc-routing)
7. [Prompt- en Beeldgeneratie](#prompt--en-beeldgeneratie)
8. [TouchDesigner](#touchdesigner)
9. [Configuratiebestanden](#configuratiebestanden)

---

## Overzicht

MUSINFO draait verdeeld over drie omgevingen: **Windows** (opname, uitzending, Windows-analysers, MIDI), **WSL2** (Essentia/ML-analysers) en **TouchDesigner** (visuals). Processen communiceren via TCP (audio) en OSC (analyseresultaten).

Processen zijn opgedeeld in twee lagen op basis van hun opstarttijd:

| Laag | Processen | Levensduur |
|---|---|---|
| **Persistent** | wsl_receiver, wsl_receiver_heavy, prompt_generator, generate_image | App start → app sluit |
| **Pipeline** | windows_receiver, broadcaster, capture, midi_capture | Start-knop → Stop-knop |

Persistente processen houden TensorFlow/Essentia-modellen in het geheugen en overleven stop/start-cycli. Pipeline-processen worden vrijelijk gestopt en herstart — ze bevatten geen blijvende toestand.

```
WINDOWS                          WSL2
───────────────────────────────  ─────────────────────────────
capture.py ──TCP:5005──► broadcaster.py ──TCP:5006──► wsl_receiver.py
                                         ──TCP:5007──► windows_receiver.py
                                         ──TCP:5008──► wsl_receiver_heavy.py
midi_capture.py (direct, geen TCP)

Alle analysers ──OSC:9000──► Tauri OSC-listener (weergave in frontend)
Alle analysers ──OSC:9100──► TouchDesigner (realtime visuele parameters)
genre / mood   ──OSC:9001──► prompt_generator.py ──OSC:9002──► generate_image.py ──NDI──► TouchDesigner
Tauri          ──OSC:9099──► TouchDesigner (pipeline-resetpuls)
```

---

## Gebruikersinterface — React + Tauri

**Locatie:** `musinfo/src/`

React 19 + Vite 7 frontend binnen een Tauri 2 desktopvenster. De UI communiceert met de Rust-backend via `invoke()` en ontvangt gebeurtenissen via `listen()`.

### Componentstructuur

```
src/
├── App.jsx                      — hoofdtoestand, pipeline-aansturing, sessiebeheer
├── components/
│   ├── layout/                  — Layout, Header, Sidebar, OutputPanel, TabContent
│   ├── tabs/
│   │   ├── Setup/               — instrument- en apparaatconfiguratie
│   │   ├── Performance/         — live MIDI-weergave en pianotoetsenbord
│   │   └── OSCConfig/           — weergave van actieve OSC-adressen voor TouchDesigner-instelling
│   ├── modal/
│   │   └── AddInstrumentModal   — formulier voor het toevoegen van een instrument
│   └── shared/
│       ├── InstrumentConfig/    — kiezer voor audioapparaat, kanaal en sample rate
│       ├── AnalyserConfig/      — schakelaars per analyser per instrument
│       ├── AudioDevicesConfig/  — apparaatlijst en reconcilatiestatus
│       ├── SignalPath/          — visuele signaalketen
│       ├── TestAudio/           — live RMS-meter per apparaatkanaal
│       └── TestMIDI/            — MIDI-gebeurtenismonitor
└── utils/
    └── roleUtils.js             — herberekent role_index-waarden binnen een rolgroep
                                   bij toevoegen, hernoemen of verwijderen van instrumenten
```

### Toestand en mutaties

`App.jsx` beheert alle centrale toestand. Elke instrumentmutatie gaat eerst via een Tauri `invoke()` om naar schijf te schrijven, daarna wordt de React-toestand bijgewerkt met het teruggegeven resultaat. `instruments.json` is altijd de enige bron van waarheid.

### Rol- en indexsysteem

Elk instrument heeft een `role`-string en een `role_index` (0-gebaseerde positie binnen die rol). Samen vormen ze het OSC-adres in TouchDesigner: `/td/{analyser}/{role}/{role_index}/{param}`. `roleUtils.js` houdt de indices aaneengesloten bij elke toevoeging, verwijdering of naamwijziging.

### Tauri-commando's

| Commando | Doel |
|---|---|
| `start_pipeline` / `stop_pipeline` | Pipeline-laagprocessen starten of stoppen |
| `get_audio_devices` / `get_midi_devices` | Apparaatlijsten ophalen (audio gecached bij opstarten) |
| `reconcile_devices` | Opgeslagen apparaatnamen koppelen aan actuele hardware |
| `save_instrument` / `delete_instrument` | Vermeldingen in instruments.json schrijven of verwijderen |
| `save_session` / `load_session` / `list_sessions` | Sessiebeheer |
| `test_device_audio` / `stop_device_test` | Live RMS-meter voor een apparaatkanaal |
| `test_midi_input` / `stop_midi_test` | MIDI-gebeurtenismonitor |
| `save_performance_config` | Geforceerde-toonsoortinstellingen opslaan in performance.json |
| `toggle_image_generation` | Beeldgeneratie in- of uitschakelen via OSC |

---

## Rust-backend — lib.rs + menu.rs

**Locatie:** `musinfo/src-tauri/src/`  
**Kernafhankelijkheden:** `tauri`, `tauri-plugin-dialog`, `serde_json` (preserve_order), `rosc`

### Proceslevenscyclus

`lib.rs` beheert twee lagen. Bij het opstarten van de app (`setup()`) worden persistente processen direct gestart — WSL-ontvangers via `wsl.exe -d Ubuntu`, beeldgeneratiescripts als Windows-Python-processen. De WSL-omgeving wordt per start geactiveerd via `source .venv/bin/activate && python3 ...`.

`start_pipeline` start de pipeline-laag in volgorde van afhankelijkheden: `windows_receiver → broadcaster → capture → midi_capture`. Nadat alle vier zijn opgestart, stuurt Tauri `/musinfo/pipeline_running 1` naar poorten 9001/9002 en een `/musinfo/reset`-puls naar poort 9099.

`stop_pipeline` sluit in omgekeerde volgorde: capture eerst (stopt audiostroom), daarna midi_capture, schrijft een stopsentinelbestand (`backend/broadcaster.stop`) en wacht 1,5 seconden voor broadcaster om zijn opname te verwerken, sluit dan broadcaster en windows_receiver. WSL-ontvangers blijven actief.

### Overige verantwoordelijkheden

- **Audioapparaatcache** — vooraf ingeladen bij opstarten in een achtergrondthread om een vertraging bij de eerste apparaatquery te voorkomen
- **OSC-listener** — bindt aan poort 9000, ontvangt analyserdata en stuurt deze door als `osc-message`-gebeurtenissen naar React
- **Instrument-CRUD** — `save_instrument` plaatst `mix` altijd als laatste item in de JSON na elke schrijfactie, ongeacht de volgorde van invoeging
- **Sessiebeheer** — opent een native bestandsdialoogvenster via `tauri-plugin-dialog`; na opslaan wordt het native menu herbouwd om de nieuwe sessie in de laadlijst te tonen

### menu.rs

Bouwt de native OS-menubalk: **Bestand** (Sessie opslaan `Ctrl+S`, submenu Sessie laden), **Help** en **Info** (openen lokale HTML-documentatie). Na elke opslag herlaadt `rebuild_menu` het submenu Sessie laden.

---

## Audiopipeline

### Omgevingen en communicatie

Audio stroomt van de audio-interface naar Python op Windows, vervolgens via TCP naar de analyselaag. Drie ontvangers draaien parallel — twee in WSL en één op Windows — elk met eigen analysers op basis van hun runtime-vereisten.

```
Audio-interface
     │ (ASIO / WASAPI / MME)
     ▼
capture.py  ──[TCP :5005]──►  broadcaster.py
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
          windows_receiver    wsl_receiver    wsl_receiver_heavy
              [:5007]             [:5006]          [:5008]
          pitch, tempo       dynamics, timbre,   genre, stemming
                             harmony, tempo_cnn,
                             pitch_crepe
```

MUSINFO ondersteunt ASIO, WASAPI en MME host-API's. De enige beperking is dat alle actieve instrumenten in een sessie dezelfde host-API moeten gebruiken — het mixen van API's binnen één capture-sessie wordt niet ondersteund.

---

### capture.py

**Locatie:** `musinfo/backend/windows/capture.py` — Windows, pipeline-laag

Leest `instruments.json` en opent één `sounddevice.InputStream` per uniek audioapparaat. Meerdere kanalen op hetzelfde apparaat delen één stream. De audio-callback vuurt bij een blokgrootte van 2048 frames, extraheert de geconfigureerde kanalen en plaatst ze in per-kanaal wachtrijen. Afzenderthreads verwerken deze wachtrijen en schrijven geframede data naar broadcaster.

Apparaatindices worden bij opstarten opgelost via naam + host-API-string, zodat hardware-herenummering tussen sessies de routing niet verstoort.

**Frame-indeling (capture → broadcaster):**
```
[1 byte ] kanaal-ID (uint8)
[4 bytes] datalengte (uint32, big-endian)
[N bytes] ruwe float32 PCM
```

---

### broadcaster.py

**Locatie:** `musinfo/backend/windows/broadcaster.py` — Windows, pipeline-laag

Het centrale routeringspunt. Luistert op TCP :5005 voor capture.py en maakt verbinding met de drie ontvangers als TCP-client. Leest `instruments.json` en `analysers.json` om een routeringstabel op te bouwen: kanaal → instrument → {wsl_analysers, wsl_heavy_analysers, windows_analysers}. Het WSL-host-IP wordt dynamisch opgelost via `ip route show default`.

De configuratie wordt elke 2 seconden opnieuw geladen (MD5-hashvergelijking), zodat instrumentwijzigingen van kracht worden zonder de pipeline te herstarten.

**Frame-indeling (broadcaster → ontvangers):**
```
[4 bytes] JSON-headerlengte (uint32, big-endian)
[N bytes] JSON: { instrument, analysers, role, role_index, instrument_index }
[4 bytes] audiolengte (uint32, big-endian)
[N bytes] ruwe float32 PCM
```

**Interne mix:** Wanneer een mix-instrument is geconfigureerd, verzamelt broadcaster chunks van alle bronkanalen in tijdsgebaseerde wachtrijen. Zodra alle bronnen een chunk hebben aangeleverd (of een stiltetijdslimiet van 150 ms is overschreden), worden de kanalen gemiddeld met numpy, waarbij niet-overeenkomende sample rates worden geresampeld via `scipy.signal.resample_poly`. De mix wordt vervolgens als eigen instrument gerouteerd.

Bij stoppen detecteert broadcaster het sentinelbestand `backend/broadcaster.stop` dat Tauri schrijft, slaat een WAV-opname op van alle ontvangen audio in `backend/audio_debug/` en sluit netjes af.

---

### windows_receiver.py

**Locatie:** `musinfo/backend/windows/windows_receiver.py` — Windows, pipeline-laag  
**Poort:** TCP :5007  
**Analysers:** `pitch`, `tempo`

Wacht op een verbinding van broadcaster. Bij verbinding initialiseert het één analyser-instantie per instrument per geconfigureerde analyser. Elke analyser draait in een `ThreadedAnalyser` — een wachtrij-gebaseerde werkthread die de TCP-ontvangstlus ontkoppelt van de analyse. Als de wachtrij vol is, wordt de oudste chunk verwijderd om de analyse actueel te houden. Bij verbreking worden alle werkthreads netjes gestopt en het register gewist.

---

### wsl_receiver.py

**Locatie:** `musinfo/backend/wsl/wsl_receiver.py` — WSL, persistente laag  
**Poort:** TCP :5006  
**Analysers:** `pitch_crepe`, `dynamics`, `timbre`, `harmony`, `tempo` (TempoCNN)

Zelfde architectuur als windows_receiver. Persistent — overleeft stop/start om Essentia-modellen geladen te houden. Het analyserregister wordt gewist bij elke nieuwe broadcaster-verbinding, maar alle Python-imports en geladen modellen blijven in het geheugen.

Wachtrijgroottes weerspiegelen de rekenkosten: `harmony` = 32 (accumuleert audio voor akkoorddetectie), `dynamics` + `timbre` = 4, `pitch_crepe` = 2, `tempo` = 1.

---

### wsl_receiver_heavy.py

**Locatie:** `musinfo/backend/wsl/wsl_receiver_heavy.py` — WSL, persistente laag  
**Poort:** TCP :5008  
**Analysers:** `genre`, `stemming`

Afzonderlijk proces voor GPU-intensieve analysers. Hierdoor kunnen genre en stemming de overige analysers niet vertragen. Beide delen de GPU via `SharedEmbedder`'s vergrendeling. Wachtrijgrootte is 1 voor beide — alleen het meest recente audioframe is relevant voor contextuele classificatie.

---

### midi_capture.py

**Locatie:** `musinfo/backend/windows/midi_capture.py` — Windows, pipeline-laag

Peilt MIDI-apparaten via `pygame.midi.Input` met 5 ms-intervallen. Gebeurtenissen (noot aan/uit, sustainpedaal, controleverandering, toonhoogtebocht) worden rechtstreeks doorgegeven aan een `MidiHarmonyAnalyser`-instantie in hetzelfde proces — geen TCP, geen WSL. Apparaatresolutie gebruikt eerst exacte naamovereenkomst, daarna basisnaam-fuzzy-matching om Windows MME-herenummering op te vangen.

---

## Analysers

Alle analysers implementeren `push(audio: np.ndarray)` en houden een interne buffer bij, waarbij audio wordt geaccumuleerd totdat er voldoende context beschikbaar is. Resultaten worden via OSC verstuurd na elke analyseslag.

Elke analyser stuurt naar twee OSC-bestemmingen:
- **Poort 9000** — frontend-monitoring (op instrumentnaam gebaseerde adressen, altijd vast)
- **Poort 9100** (of 9001 voor contextuele analysers) — TouchDesigner / promptgenerator (op rol gebaseerde adressen)

---

### Windows-analysers (`musinfo/backend/windows/analysers/`)

#### pitch_analyser.py
**Algoritme:** Aubio YIN / YinFFT  
**Frontend (9000):** `/pitch/{naam}` — nootnaam + Hz-string  
**TouchDesigner (9100):** `/td/pitch/{rol}/{rol_index}/hz`

Snelle YIN-toonhoogtedetectie. Gefilterd op een instelbaar Hz-bereik met een minimale betrouwbaarheidsdrempel.

#### tempo_analyser.py
**Algoritme:** Aubio beat tracker  
**Frontend (9000):** `/tempo/{naam}/pulse`, `/tempo/{naam}/bpm`  
**TouchDesigner (9100):** `/td/tempo/pulse` — beatpuls (1, daarna 0)

Beatpuls vuurt bij elke gedetecteerde beat en reset op het volgende frame. BPM wordt eenmaal per seconde verstuurd als mediaan van recente slagintervallen, afgevlakt over 8 beats.

#### midi_harmony_analyser.py
**Algoritme:** Krumhansl-Schmuckler toonsoortdetectie + sjabloonakkoordherkenning + Plomp-Levelt dissonantie (alles numpy, geen Essentia)  
**Gestart door:** `midi_capture.py` direct — niet via windows_receiver  
**Frontend (9000):** `/harmony/{naam}` (volledige JSON), `/harmony/{naam}/frontend` (vereenvoudigd)  
**TouchDesigner (9100):** `/td/harmony/{rol}/{rol_index}/key`, `scale`, `chord`, `chord_quality`, `chord_strength`, `roman_degree`, `dissonance`, `harmonic_change`, `hpcp`

Werkt op basis van exacte MIDI-nootkennis — geen spectrale schatting nodig. Bouwt een snelheidsgewogen toonklassehistogram op en correleert dit met Krumhansl-Schmuckler-profielen voor 12 grondtonen. Toonsoortwijzigingen vereisen KS_KEY_LOCK opeenvolgende overeenkomsten. Ondersteunt geforceerde-toonsoortmodus (elke seconde herladen uit `performance.json`).

---

### WSL-analysers (`musinfo/backend/wsl/analysers/`)

#### dynamics_analyser.py
**Algoritme:** Essentia OnsetDetection + Onsets (adaptieve piekdetectie)  
**Frontend (9000):** `/dynamics/{naam}/rms`, `onset`, `onset_strength`, `rms_at_onset`  
**TouchDesigner (9100):** `/td/dynamics/{rol}/{rol_index}/rms`, `onset`, `onset_strength`, `rms_at_onset`

RMS wordt afgevlakt met een EMA (α = 0,3) en geschaald naar een bereik van 0–100. Aanzetdetectie gebruikt Essentia's complexe ODF over een rolraam van 1 seconde.

#### timbre_analyser.py
**Algoritme:** Spectrale analyse (Essentia) + HFC-aanzetdetectie  
**Frontend (9000):** `/timbre/{naam}/centroid`, `rolloff`, `flatness`, `flux`, `mfcc_delta`, `mfcc`, `attack`  
**TouchDesigner (9100):** `/td/timbre/{rol}/{rol_index}/{param}` — zelfde set

Alle continue descriptoren worden EMA-afgevlakt (α = 0,3). Aanvaltijd wordt gemeten door een HFC-onset te detecteren en vervolgens Essentia's `LogAttackTime` toe te passen op het 150 ms-venster na de onset.

#### harmony_analyser.py
**Algoritme:** SpectralPeaks → HPCP → ChordsDetection → Key → Dissonantie (Essentia), optionele HPSS via librosa  
**Frontend (9000):** `/harmony/{naam}` (volledig JSON-resultaat), `/harmony/{naam}/frontend` (vereenvoudigd)  
**TouchDesigner (9100):** `/td/harmony/{rol}/{rol_index}/chord`, `chord_quality`, `chord_strength`, `roman_degree`, `key`, `scale`, `dissonance`, `harmonic_change`, `hpcp`

Verwerkt audio in 4096-sample frames met 50% overlap. Akkoordlabels worden afgevlakt over een 9-frame geschiedenis. Toonsoort wordt gedetecteerd op een 20-frame buffer en moet 60% van een 10-frame historievenster bevatten voor aanvaarding. HPSS is standaard uitgeschakeld (`HPSS_ENABLED = False`). Ondersteunt geforceerde-toonsoortmodus. OSC wordt beperkt tot elke 10 frames (~430 ms bij 48 kHz).

#### pitch_crepe_analyser.py
**Algoritme:** CREPE (Essentia — crepe-medium of crepe-large model)  
**Modelsnelheid:** 16000 Hz (audio wordt voor inferentie geresampeld)  
**Frontend (9000):** `/pitch_crepe/{naam}` — nootnaamstring  
**TouchDesigner (9100):** `/td/pitch/{rol}/{rol_index}/hz`

Verwerkt 200 ms-vensters bij 16 kHz. Het frame met de hoogste betrouwbaarheid wordt verstuurd als het de minimale betrouwbaarheidsdrempel (0,6) overschrijdt.

#### tempo_cnn_analyser.py
**Algoritme:** TempoCNN (Essentia — deepsquare-k16-3 model)  
**Modelsnelheid:** 11025 Hz (audio wordt voor inferentie geresampeld)  
**Frontend (9000):** `/tempo/{naam}/bpm_accurate`, `/tempo/{naam}/feel`  
**Promptgenerator (9001):** `/prompt/tempo_feel`

Accumuleert ~12 seconden audio bij 11025 Hz voor de eerste inferentie. BPM wordt afgevlakt over 3 voorspellingen. Het feelabel (`ballad`, `slow`, `medium`, `uptempo`, `fast`) wordt alleen verstuurd wanneer de bucket verandert.

#### genre_analyser.py
**Algoritme:** Discogs-EffNet embeddings → 400-klassen genreclassificator (Essentia)  
**Frontend (9000):** `/genre/{naam}` — JSON-array van top-3 genre/betrouwbaarheidsparen  
**Promptgenerator (9001):** `/prompt/genre`

Analyseert 4-seconden-vensters bij 16 kHz met 50% hop. Voorspellingen worden gekoppeld van 400 Discogs-genres naar 14 bredere stijlbuckets. GPU-aanroepen worden gerouteerd via de vergrendeling van `SharedEmbedder`.

#### mood_analyser.py
**Algoritme:** Discogs-EffNet embeddings → 5 binaire stemmingsclassificatoren + dansbaarhied + Jamendo meerlabelclassificatie (Essentia)  
**Frontend (9000):** `/mood/{naam}/top`, `/mood/{naam}/danceability`, `/mood/{naam}/tags`  
**Promptgenerator (9001):** `/prompt/mood`, `/prompt/danceability`, `/prompt/mood_tags`

Drie onafhankelijke audiobuffers (stemming, dansbaarhied, Jamendo) vuren met 3-seconden-intervallen, verspringend met 1-seconde-offsets om gelijktijdige GPU-aanroepen te vermijden. `positive_class_index` is per model ingesteld — de positieve klasse staat niet altijd op index 1 in Essentia's softmax-uitvoer.

#### shared_embedder.py
**Locatie:** `musinfo/backend/wsl/analysers/shared_embedder.py`

Singleton die Discogs-EffNet éénmalig laadt (uitvoer `PartitionedCall:1`, 1280-dimensionale embeddings) en `get_embeddings()` en `get_predictions()` beschikbaar stelt onder één `_gpu_lock`. Genre en stemming roepen dit aan vanuit afzonderlijke threads; de vergrendeling zorgt ervoor dat slechts één GPU-inferentie tegelijk plaatsvindt.

---

## OSC-routing

MUSINFO gebruikt twee afzonderlijke OSC-poorten voor analyseuitvoer — één voor de frontend en één voor TouchDesigner.

**Poort 9000 — Tauri-frontend (op instrumentnaam gebaseerd)**  
Alle analysers sturen hun resultaten hierheen. Adressen zijn vast en gebaseerd op instrumentnaam — ze veranderen niet op basis van rol of sessieconfiguratie.

```
/pitch/{naam}                    → nootnaam + Hz-string
/tempo/{naam}/pulse              → beatpuls (1)
/tempo/{naam}/bpm                → BPM (float)
/dynamics/{naam}/rms             → 0–100 float
/dynamics/{naam}/onset           → 0 of 1
/timbre/{naam}/centroid          → Hz float
/harmony/{naam}                  → volledig JSON-resultaat
/harmony/{naam}/frontend         → vereenvoudigd JSON-subset
/genre/{naam}                    → JSON-array
/mood/{naam}/top                 → stemmingslabel (string)
/mood/{naam}/danceability        → 0–100 float
/mood/{naam}/tags                → kommagescheiden string
```

**Poort 9100 — TouchDesigner (op rol/rol_index gebaseerd)**  
Alle realtime visuele parameters. Adressen bevatten de `role` en `role_index` van het instrument, zoals geconfigureerd in het Instellen-tabblad van MUSINFO.

```
/td/pitch/{rol}/{rol_index}/hz
/td/tempo/pulse
/td/dynamics/{rol}/{rol_index}/rms
/td/dynamics/{rol}/{rol_index}/onset
/td/dynamics/{rol}/{rol_index}/onset_strength
/td/dynamics/{rol}/{rol_index}/rms_at_onset
/td/timbre/{rol}/{rol_index}/centroid
/td/timbre/{rol}/{rol_index}/rolloff
/td/timbre/{rol}/{rol_index}/flatness
/td/timbre/{rol}/{rol_index}/flux
/td/timbre/{rol}/{rol_index}/mfcc_delta
/td/timbre/{rol}/{rol_index}/mfcc
/td/timbre/{rol}/{rol_index}/attack
/td/harmony/{rol}/{rol_index}/chord
/td/harmony/{rol}/{rol_index}/chord_quality
/td/harmony/{rol}/{rol_index}/chord_strength
/td/harmony/{rol}/{rol_index}/roman_degree
/td/harmony/{rol}/{rol_index}/key
/td/harmony/{rol}/{rol_index}/scale
/td/harmony/{rol}/{rol_index}/dissonance
/td/harmony/{rol}/{rol_index}/harmonic_change
/td/harmony/{rol}/{rol_index}/hpcp
```

**Poort 9001 — prompt_generator.py**

```
/prompt/genre                    → JSON-string
/prompt/mood                     → stemmingslabel
/prompt/danceability             → float
/prompt/mood_tags                → kommagescheiden string
/prompt/tempo_feel               → string
/musinfo/pipeline_running        → 0 of 1 (vanuit Tauri)
/musinfo/image_gen_enabled       → 0 of 1 (vanuit Tauri)
```

**Poort 9099 — TouchDesigner reset**  
`/musinfo/reset` — puls (1 dan 0) verstuurd door Tauri bij pipeline-start en -stop.

---

## Prompt- en Beeldgeneratie

**Locatie:** `AI_image_generation/` (in de repositoryroot, buiten `musinfo/`)

### prompt_generator.py
Luistert op OSC :9001. Accumuleert genre-, stemming-, temposfeer- en harmoniecontext en stelt een natuurlijke-taalomschrijving samen van de muzikale sfeer. De voltooide prompt wordt verstuurd naar `generate_image.py` op :9002. Generatie wordt onderdrukt wanneer `pipeline_running` of `image_gen_enabled` 0 is.

### generate_image.py
Luistert op OSC :9002. Ontvangt prompts en voert inferentie uit via SD Turbo (lokaal op de NVIDIA GPU). Gegenereerde beelden worden via NDI naar TouchDesigner gestuurd. Dit proces behoort tot de persistente laag — het model wordt geladen bij het opstarten van de app.

---

## TouchDesigner

**Bestand:** `touchdesigner/Harmonic_Visuals.toe`

Ontvangt alle realtime parameters op OSC :9100 en koppelt deze aan visuele eigenschappen. Kernarchitectuur:

- Eén **OSC In CHOP** per actief adres — adressen komen overeen met de rol/rol_index-configuratie uit MUSINFO
- Beatpuls (:9100 `/td/tempo/pulse`) gerouteerd via Trail/Lag CHOP-keten naar een Transform TOP voor schaalgebaseerde pulseffecten
- AI-beelden worden ontvangen via **NDI In TOP** en overgecrossfade met Info CHOP + Logic CHOP + Trigger CHOP + Cross TOP + Cache TOP
- CHOP Execute DAT monitort het aantal actieve instrumenten en past de lay-out aan
- Toegewijd OSC-ontvanger op :9099 verwerkt `/musinfo/reset`-pulsen van Tauri

---

## Configuratiebestanden

**Locatie:** `musinfo/backend/config/`

**instruments.json** — primaire configuratie en enige bron van waarheid. Bevat alle instrumentdefinities. Alle routeringsbeslissingen in broadcaster.py, alle ontvangers en de React-UI zijn hiervan afgeleid.

**analysers.json** — definieert alle beschikbare analysers, hun `target`-ontvanger (`windows`, `wsl`, `wsl_heavy` of `both`) en standaard ingeschakelde toestand. broadcaster.py leest dit om de analyserlijst van elk instrument op te splitsen per ontvanger.

**performance.json** — configuratie voor geforceerde toonsoort (`forcedKey.enabled`, `key`, `scale`), elke seconde opnieuw geladen door harmony_analyser.py en midi_harmony_analyser.py.

---

*Architectuurdocumentatie opgesteld met behulp van Claude Sonnet 4.6.*
