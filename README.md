# Contemplay — Banco de Cotas Ademicon

Dashboard online do banco de cotas contempladas, com atualização automática via vídeo.

## Stack
- **Frontend**: HTML/CSS/JS puro — sem framework, zero dependências
- **Deploy**: GitHub + Vercel (static hosting)
- **Atualização**: Script Python com Claude API (OCR dos vídeos)

---

## Setup inicial (uma vez só)

### 1. Clonar e instalar dependências
```bash
git clone https://github.com/SEU_USUARIO/contemplay.git
cd contemplay
pip install anthropic python-dotenv
```

### 2. Configurar variáveis de ambiente
```bash
cp .env.example .env
# Editar .env com seus valores
```

### 3. Criar repositório no GitHub
```bash
git init
git add .
git commit -m "feat: setup inicial contemplay"
git remote add origin https://github.com/SEU_USUARIO/contemplay.git
git push -u origin main
```

### 4. Deploy no Vercel
1. Acesse [vercel.com](https://vercel.com) → **Add New Project**
2. Importe o repositório `contemplay`
3. **Framework Preset**: Other
4. **Root Directory**: deixar em branco (usa `vercel.json`)
5. Clique **Deploy**

A URL ficará no formato: `https://contemplay.vercel.app`

---

## Atualizar o banco de cotas

Sempre que você receber um novo vídeo do Banco de Cotas, rode:

```bash
python scripts/contemplay_update.py --video caminho/do/video.mp4
```

O script vai:
1. Extrair ~46 frames do vídeo (ffmpeg)
2. Enviar para Claude API para extração OCR das cotas
3. Substituir os dados no `public/index.html`
4. Fazer `git commit + push` para o GitHub
5. Vercel redeploy automático em ~30 segundos

### Opções
```bash
# Só atualizar o HTML, sem push (para testar)
python scripts/contemplay_update.py --video video.mp4 --no-push

# Ajustar frequência de frames (padrão: 1 frame a cada 3s)
python scripts/contemplay_update.py --video video.mp4 --fps 1/2
```

---

## Estrutura do projeto

```
contemplay/
├── public/
│   └── index.html          ← Dashboard (dados embutidos inline)
├── scripts/
│   └── contemplay_update.py ← Plugin de atualização
├── .env.example
├── .gitignore
├── vercel.json
└── README.md
```

---

## Como o CET é calculado

Usa a função `=TAXA()` do Excel, implementada via Newton-Raphson:

```
=TAXA(prazo; -parcela; crédito - entrada)
```

- **VP** = Crédito − Entrada (valor líquido recebido)
- **PGTO** = −Parcela (saída de caixa mensal)
- **NPER** = Prazo restante em meses
- **Resultado** = CET a.m. (idêntico ao Excel)

---

## Token do GitHub

Gere em: **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**

Permissões necessárias:
- **Contents**: Read and write
- **Metadata**: Read-only
