# OpenCorsairRGB

**Controle de iluminação RGB de código aberto para Linux** — memória Corsair Vengeance RGB PRO SL, placas de vídeo ASUS (ENE), header ARGB de placas-mãe COLORFUL e o display digital do water cooler GAMDIAS CHIONE, tudo em um único app GTK4.

> 🇺🇸 English: [README.md](README.md)

---

## Funcionalidades

- 🎨 **Efeitos:** estático, arco-íris, espectro, gradiente, alternar cores e onda de cores, com 2 a 6 cores, velocidade e brilho
- ⚡ **Estilos prontos:** Arco-íris, Espectro, Cyberpunk, Fogo, Oceano, Aurora, Pôr do sol, Natal
- 🔗 **Sincronizar** todos os dispositivos ou configurar cada um separadamente
- 🌡️ **Display do water cooler:** temperatura da CPU ao vivo (°C/°F) no bloco da bomba, com alarme piscando
- 🖥️ **App nativo do GNOME** (GTK 4 + libadwaita) e **linha de comando**
- 🔁 **Serviço em segundo plano** mantém as animações e restaura tudo ao entrar na sessão
- 🔓 **Sem root no uso diário** — regras udev liberam o acesso aos dispositivos

## Hardware suportado

| Dispositivo | Interface | ID / endereço |
|---|---|---|
| **Corsair Vengeance RGB PRO SL** (DDR4) | SMBus | `0x58`–`0x5B` |
| **ASUS ROG STRIX RTX 3080 White OC** e outras GPUs ASUS com ENE | i2c NVIDIA | `0x67` |
| **Header ARGB COLORFUL** (ex.: CVN B550M GAMING FROZEN) | USB HID | `2f4c:1000` |
| **Display digital GAMDIAS CHIONE E4** | USB HID | `1b80:b53c` |

Testado no **Linux Mint 22.3** (base Ubuntu 24.04), GNOME, kernel 7.0.

## Instalação

### Opção 1 — pacote `.deb` (Debian, Ubuntu, Linux Mint, Pop!_OS)

Baixe o `opencorsairrgb_<versão>_all.deb` na página **Releases** e rode:

```bash
sudo apt install ./opencorsairrgb_*_all.deb
```

Saia e entre de novo na sessão (ou reinicie) para as permissões e o serviço valerem.
Depois abra **OpenCorsairRGB** no menu de aplicativos.

### Opção 2 — gerar o pacote a partir do código

```bash
sudo apt install git python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
git clone https://github.com/<seu-usuario>/OpenCorsairRGB.git
cd OpenCorsairRGB
./build-deb.sh
sudo apt install ./build/opencorsairrgb_*_all.deb
```

### Opção 3 — rodar sem instalar (desenvolvimento)

```bash
# uma vez: permissões
sudo cp data/61-opencorsairrgb.rules /etc/udev/rules.d/
sudo modprobe i2c-dev
sudo udevadm control --reload && sudo udevadm trigger

# terminal 1: serviço
python3 -m opencorsairrgb.cli --daemon
# terminal 2: app
python3 -m opencorsairrgb.cli
```

## Como usar

### App

Abra **OpenCorsairRGB** no menu (ou rode `opencorsairrgb`). Tudo é aplicado na hora:

- **Estilos / cores sólidas** — um clique aplica em todos os dispositivos ligados
- **Sincronizar** — fans, memória e GPU com o mesmo efeito
- Cada dispositivo tem **Ligado, Efeito, Cores (+/−), Velocidade e Brilho**
- **Memória ⟳** — reenviar para os pentes que não mudaram
- **Display do water cooler** — ligar, unidade e limite do alarme

### Terminal

```bash
opencorsairrgb --status
opencorsairrgb --fans ff00ff
opencorsairrgb --gpu rainbow
opencorsairrgb --ram spectrum
opencorsairrgb --fans wave:ff00ff,00e5ff,ffffff
opencorsairrgb --gpu gradient:ff3c00,6a00ff
opencorsairrgb --ram off
opencorsairrgb --display on|off|c|f
```

### Serviço

```bash
systemctl --user status opencorsairrgb
systemctl --user restart opencorsairrgb
journalctl --user -u opencorsairrgb -f
```

Configurações: `~/.config/opencorsairrgb/config.json`.

## Limitações conhecidas

- **Memória Corsair:** na placa testada o chip RGB recusa ~70% dos comandos SMBus, então o driver repete muito. Cores fixas levam 10–30 s e às vezes só 2–3 de 4 pentes mudam — use o botão ⟳. Efeitos de firmware ficam **salvos no pente**; *alternar* e *onda* usam só as 2 primeiras cores.
- **GPU:** *arco-íris* e *espectro* usam os efeitos do próprio firmware ENE da placa (suaves, sem gastar CPU; o brilho não se aplica a eles). *Alternar* e *onda* não existem no firmware e são desenhados pelo serviço a 4 fps — cada quadro são ~44 transações i2c e o driver NVIDIA consome CPU esperando, então esses dois efeitos pesam. Nada é salvo na placa: até o serviço iniciar, ela mostra o efeito salvo pelo software do fabricante.
- **Display:** o modo de RPM do fan não foi implementado.

## Problemas comuns

| Problema | Solução |
|---|---|
| "Sem permissão" | Saia e entre na sessão; `ls -l /dev/hidraw* /dev/i2c-*` deve mostrar `+` |
| GPU / memória não encontrada | `sudo modprobe i2c-dev`; confira `i2cdetect -l` |
| Aviso "serviço parado" | `systemctl --user enable --now opencorsairrgb` |
| Display continua `----` | Verifique se o serviço está ativo e a opção do display ligada |
| Conflito com OpenRGB | Não use o OpenRGB nos mesmos dispositivos ao mesmo tempo |

## Desinstalar

```bash
sudo apt remove opencorsairrgb
rm -rf ~/.config/opencorsairrgb ~/.local/state/opencorsairrgb   # opcional
```

## Aviso

Projeto independente, **sem vínculo** com Corsair, ASUS, COLORFUL, GAMDIAS ou NVIDIA. As marcas pertencem aos seus donos. Escrever em registradores de hardware é por sua conta e risco.

## Licença

[GPL-2.0-or-later](LICENSE)
