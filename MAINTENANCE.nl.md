# MUSINFO — Onderhoud

Dit document behandelt het onderhoud van de codebase, het toevoegen van nieuwe analysers en bekende problemen met tijdelijke oplossingen.

---

## NAAMGEVINGSCONVENTIES

**Python-bestanden** — `snake_case` door de hele codebase: `pitch_analyser.py`, `windows_receiver.py`, `midi_capture.py`. Elk bestand opent met een commentaarblok:

```python
# bestandsnaam.py — Korte eenregelige beschrijving
# Wat dit bestand doet, waarmee het verbinding maakt.
```

Sectieafscheidingen gebruiken hoofdletters als visuele scheiding — dit wordt gestandaardiseerd tijdens de codeopruiming.

`INFO`- en `DEBUG`-constanten bovenaan elk bestand sturen alle printuitvoer. Elk printstatement bevat het bestandsnaamprefix: `[bestandsnaam] bericht`.

**Analyserklassen** — `push(audio: np.ndarray)` is de enige publieke methode. OSC-adressen worden opgebouwd uit constructorargumenten (`instrument_role`, `role_index`), niet als vaste strings verspreid door de logica.

**React-componenten** — één component per bestand, CSS Modules door de hele codebase, props worden bovenaan elke componentfunctie gedestructureerd. Handlefuncties in `App.jsx` krijgen het voorvoegsel `handle` en worden doorgegeven als `on`-props.

**Tauri-commando's** — `snake_case`, overeenkomend met de `invoke()`-aanroep in React. Elk commando geeft een getypeerde waarde of een foutstring terug.

---

## AI-TRANSPARANTIE

Claude Sonnet 4.6 is gebruikt voor implementatieondersteuning gedurende het hele project. De volgende principes zijn toegepast:

- Architectuurbeslissingen werden genomen door de ontwikkelaar. De AI kreeg een afgebakend probleem en bestaande codecontext, niet de opdracht het systeem te ontwerpen.
- Alle gegenereerde code werd beoordeeld vóór het committen. Inconsistente naamgeving of structurele afwijkingen werden handmatig gecorrigeerd.
- Halluccinaties werden opgespoord door kruiscontrole met Essentia-documentatie, Tauri-documentatie en daadwerkelijk runtimegedrag. De AI werd niet vertrouwd op modeluitvoervormen of ASIO-threading-vereisten.

Een volledig overzicht van AI-gesprekken staat in `README.nl.md` onder *Gebruik van AI bij Ontwikkeling*.

---

## COMMIT-CONVENTIES

```
feat:     nieuwe functionaliteit
fix:      bugoplossing
refactor: codeherstructurering zonder gedragswijziging
chore:    build, configuratie, tooling (zelden gebruikt)
```

Documentatiewijzigingen worden gecommit op een aparte `documentation`-branch.

---

## EEN ANALYSER TOEVOEGEN

### Stap 1 — Schrijf de analyser

Maak het bestand aan in de juiste map:
- `musinfo/backend/windows/analysers/` — Windows (Aubio, numpy, pygame)
- `musinfo/backend/wsl/analysers/` — WSL (Essentia, TensorFlow, librosa)

Minimale structuur:

```python
# mijn_analyser.py — Korte beschrijving
# Wat het analyseert, wat het verstuurt.

import numpy as np
import subprocess
from pythonosc import udp_client

def _get_windows_host_ip():  # alleen nodig voor WSL-analysers
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

OSC_HOST    = _get_windows_host_ip()   # "127.0.0.1" voor Windows-analysers
OSC_PORT    = 9000   # Tauri-frontend
OSC_TD_PORT = 9100   # TouchDesigner

MIN_SAMPLES = 4096

class MijnAnalyser:
    def __init__(self, instrument_name, sample_rate, instrument_role="default",
                 role_index=0, instrument_index=0):
        self.instrument_name = instrument_name
        self.instrument_role = instrument_role
        self.role_index      = role_index
        self._buffer         = np.array([], dtype=np.float32)
        self._osc            = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self._td             = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)

    def push(self, audio: np.ndarray):
        self._buffer = np.concatenate([self._buffer, audio])
        if len(self._buffer) < MIN_SAMPLES:
            return
        resultaat = self._analyseer(self._buffer[-MIN_SAMPLES:])
        # Frontend-adres — op instrumentnaam gebaseerd, altijd vast
        self._osc.send_message(f"/mijn_analyser/{self.instrument_name}/resultaat", float(resultaat))
        # TD-adres — op rol/index gebaseerd, overeenkomend met OSC-configuratietabblad
        self._td.send_message(f"/td/mijn_analyser/{self.instrument_role}/{self.role_index}/resultaat", float(resultaat))

    def _analyseer(self, audio: np.ndarray) -> float:
        return 0.0
```

### Stap 2 — Een model toevoegen (indien nodig)

Plaats modelbestanden in een aparte submap:

```
musinfo/backend/wsl/models/mijn_analyser_modellen/
    mijn_model-1.pb
    mijn_model-1.json
```

**Commit modelbestanden nooit naar de repository.** Ze moeten handmatig worden opgeslagen en verspreid (bijv. via Hugging Face of een gedeelde schijf). Essentia-modeldocumentatie en downloads zijn beschikbaar op [essentia.upf.edu/models](https://essentia.upf.edu/models/).

### Stap 3 — Registreer in analysers.json

```json
"mijn_analyser": {
    "target": "wsl",
    "enabled_by_default": false,
    "description": "Korte beschrijving"
}
```

`target` kan `"windows"`, `"wsl"`, `"wsl_heavy"` of `"both"` zijn. Bij `"both"` routeert broadcaster de audio gelijktijdig naar zowel de WSL- als de Windows-ontvanger. Dit is nuttig wanneer meerdere analyserbestanden samenwerken voor één type analyse (zoals Tempo, dat zowel TempoCNN in WSL als Aubio in Windows gebruikt).

### Stap 4 — Registreer in de ontvanger

Importeer en voeg toe aan `AVAILABLE_ANALYSERS` in het doelontvangerbestand:

```python
from analysers.mijn_analyser import MijnAnalyser

AVAILABLE_ANALYSERS = {
    ...
    "mijn_analyser": MijnAnalyser,
}
```

Stel een wachtrijgrootte in bij `ANALYSER_QUEUE_SIZES`. De wachtrij bepaalt hoeveel audiochunks kunnen wachten voordat de oudste wordt verwijderd. Grotere wachtrijen tolereren tragere analysers zonder frames te verliezen, maar vergroten de latentie. Houd GPU-zware analysers op 1–2 (voorkeur voor actuele data boven volledigheid), snelle CPU-analysers op 4 of meer.

```python
ANALYSER_QUEUE_SIZES = {
    ...
    "mijn_analyser": 4,
}
```

### Stap 5 — Frontend

De schakelaar voor de analyser verschijnt automatisch in het AnalyserConfig-component zodra de vermelding in `analysers.json` aanwezig is. Er zijn geen React-wijzigingen nodig.

---

## BEKENDE PROBLEMEN

### SD Turbo CUDA-fout — verouderde GPU-toestand bij herstart

**Symptoom:** `generate_image.py` geeft een CUDA-fout na het stoppen en herstarten van de pipeline. De fout betreft doorgaans een verouderde CUDA-context of een mislukte GPU-bewerking.

**Tijdelijke oplossing:** Wis de CUDA-context vanuit een WSL-terminal vóór het herstarten:

```python
python -c "import torch; torch.cuda.empty_cache(); torch.cuda.synchronize(); print('CUDA gewist')"
```

**Oorzaak:** `generate_image.py` behoort tot de persistente laag en initialiseert zijn GPU-toestand niet volledig opnieuw wanneer de pipeline herstart. Een definitieve oplossing zou een nette herinitialisatie toevoegen, getriggerd door `/musinfo/pipeline_running`.

---

### Een falende analyser kan andere analysers beïnvloeden

**Symptoom:** Een onafgehandelde uitzondering in de `push()`-methode van één analyser laat het ontvangerproces mogelijk niet crashen, maar als het gedeelde toestand beschadigt of de `ThreadedAnalyser`-werkthread blokkeert, kunnen andere analysers in dezelfde ontvanger stoppen met produceren zonder duidelijke foutmelding.

**Diagnose:** Zet `DEBUG = True` en/of `INFO = True` bovenaan het betreffende analyserbestand en herstart de pipeline. De uitgebreide uitvoer toont welke analyser fouten genereert. De `ThreadedAnalyser` in elke ontvanger vangt uitzonderingen op en print ze in `_worker()`, zodat de fout zichtbaar is in de procesuitvoer.

**Opmerking:** Genre en stemming delen GPU-resources via `SharedEmbedder`. Als de embedder uitvalt (bijv. door de CUDA-verouderde-toestand-bug), stoppen zowel genre als stemming gelijktijdig met het produceren van resultaten.

---

### WSL-host-IP niet correct opgelost in broadcaster.py

**Symptoom:** Alle WSL-gebaseerde analyse stopt als het WSL-host-IP verouderd raakt na een WSL-reset of netwerkwijziging. WSL wijst bij elke opstart een nieuw virtueel gateway-IP toe.

**Oplossing:** broadcaster.py lost het WSL-host-IP dynamisch op via `ip route show default`, overeenkomend met hetzelfde patroon dat wordt gebruikt in alle WSL-analysers:

```python
def _get_wsl_host_ip():
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"   # terugvalwaarde
```

Als OSC-berichten van WSL-analysers niet meer aankomen, controleer dan het gateway-IP handmatig (`ip route show default` in WSL) en verifieer of het overeenkomt met de terugvalwaarde.

---

### Audioapparaatindex verandert tussen sessies

**Symptoom:** Na een systeemherstart of herverbinding van een USB-apparaat kan een ander geheel getal aan hetzelfde fysieke apparaat worden toegewezen.

**Oplossing:** `resolve_device_id()` in `capture.py` matcht op apparaatnaam + host-API-string, niet op geheel getal. `reconcile_devices` wordt automatisch uitgevoerd bij pipeline-start en sessieladen. Als een apparaat als niet verbonden wordt weergegeven terwijl het fysiek aanwezig is, gebruik dan de reconciliatieknop in AudioDevicesConfig of herstart de app.
