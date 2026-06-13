# QuantumBot v1.0.0

QuantumBot è un progetto desktop Python per macOS dedicato allo studio, al portfolio e alla simulazione di strategie su criptovalute.

L'app include una dashboard Tkinter e un engine in background separato. La dashboard mostra dati, stato del bot, registro operazioni simulate e grafici Matplotlib. I dati di mercato vengono letti da Binance tramite `ccxt`, con fallback simulato quando rete o dipendenze non sono disponibili.

## Avvertenza importante

QuantumBot lavora esclusivamente in trading simulato.

Non esegue ordini reali, non invia operazioni a exchange, non gestisce API key e non deve essere considerato consulenza finanziaria. Tutte le operazioni di acquisto, vendita, Take Profit, Stop Loss e Auto Trade sono simulate localmente.

## Caratteristiche

- App desktop Python per macOS.
- Dashboard grafica in Tkinter.
- Grafici Matplotlib con backend TkAgg.
- Dati Binance tramite `ccxt`.
- Registro operazioni simulate in CSV.
- Configurazione locale in JSON.
- Engine separato dalla dashboard.
- Chiusura dashboard senza arrestare l'engine.
- Build macOS con PyInstaller in modalità `--onedir --windowed`.

## File principali

- `QuantumBot.py`: applicazione principale con dashboard ed engine.
- `requirements.txt`: dipendenze Python.
- `build_macos.sh`: script di build macOS con PyInstaller.
- `README.md`: documentazione del progetto.
- `.gitignore`: esclusioni per build, cache e file runtime locali.

## Installazione per sviluppo

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

Tkinter è normalmente incluso nelle installazioni Python per macOS distribuite da python.org. Se la dashboard non si apre, verificare che la propria installazione Python includa Tcl/Tk.

## Avvio da sorgente

```bash
python3 QuantumBot.py
```

All'avvio la dashboard prova ad avviare l'engine in background. Per fermare davvero il bot usare il pulsante dedicato nella dashboard; chiudere la finestra non interrompe l'engine.

## Build macOS

```bash
chmod +x build_macos.sh
./build_macos.sh
```

Lo script esegue:

```bash
python3 -m PyInstaller --clean --onedir --windowed --name "QuantumBot" QuantumBot.py
```

L'app compilata viene generata in `dist/QuantumBot.app` e la distribuzione `onedir` in `dist/QuantumBot/`.

## Dati locali

QuantumBot salva i file runtime nella cartella esterna dell'app, non dentro `Contents/MacOS`.

In build macOS, con `dist/QuantumBot.app`, i file vengono salvati nella cartella `dist/` accanto alla `.app`:

- `config.json`
- `status_bot.json`
- `comandi_bot.jsonl`
- `comandi_state.json`
- `registro_trade.csv`
- `engine.pid`
- `eventi_bot.log`
- `errori_bot.log`
- `engine_stdout.log`
- `engine_stderr.log`
- `engine_launch.log`

Questi file sono locali e vengono esclusi dal repository tramite `.gitignore`.

## Obiettivo del progetto

QuantumBot nasce come progetto di studio e portfolio per mostrare:

- integrazione Python desktop su macOS;
- uso di Tkinter e Matplotlib;
- lettura dati crypto tramite `ccxt`;
- separazione tra interfaccia grafica ed engine in background;
- gestione di file locali e simulazione operativa.

Il progetto non è pensato per trading reale o automazione finanziaria in produzione.
