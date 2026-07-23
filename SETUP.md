# Configuração inicial

## O que esta automação faz

- Gera a edição de abertura às 07h45, horário de São Paulo, de segunda a sexta.
- Gera a edição de fechamento às 18h15, horário de São Paulo, de segunda a sexta.
- Produz MP3, roteiro em texto e feed RSS.
- Publica os arquivos pelo GitHub Pages.

Os horários do GitHub Actions são aproximados e podem sofrer alguns minutos de atraso.

## Ativação

1. Mescle o pull request no branch `main`.
2. Abra **Settings → Pages**.
3. Em **Build and deployment → Source**, selecione **GitHub Actions**.
4. Abra **Actions → Generate market podcast → Run workflow**.
5. Escolha `abertura` para o primeiro teste.
6. Aguarde a execução terminar.
7. Confirme que `https://gui-dm.github.io/market-podcast/feed.xml` abre no navegador.

## YouTube Music

No aplicativo YouTube Music, use a opção de adicionar podcast por feed RSS e cole:

`https://gui-dm.github.io/market-podcast/feed.xml`

## Privacidade

O feed não é divulgado nem indexado como um podcast público, mas o GitHub Pages é tecnicamente público. Qualquer pessoa que obtiver o endereço poderá acessar os episódios.

## Custos e limitações

O projeto usa recursos gratuitos. Yahoo Finance, Google News RSS e a voz neural gratuita podem apresentar atrasos, indisponibilidade ou mudanças de funcionamento. As cotações devem ser tratadas como informativas, não como dados oficiais de negociação.
# Camada editorial com destaques

Para transformar as cotações e manchetes em um roteiro editorial, crie uma chave da
Gemini API no Google AI Studio e salve-a no repositório em **Settings → Secrets and
variables → Actions → New repository secret**.

- Nome: `GEMINI_API_KEY`
- Valor: a chave criada no Google AI Studio

Nunca coloque a chave diretamente em `generate.py`, `config.json` ou outro arquivo do
repositório. Se a chave estiver ausente, inválida ou o limite gratuito for atingido, o
workflow continua funcionando e publica automaticamente o roteiro determinístico.

