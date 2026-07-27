# Configuração inicial

## O que esta automação faz

- Tenta a edição de abertura a partir das 07h47, horário de São Paulo, de segunda a sexta.
- Tenta a edição de fechamento a partir das 18h17, horário de São Paulo, de segunda a sexta.
- Repete automaticamente a tentativa dentro da janela de cada edição se houver falha.
- Não gera duplicidade quando MP3, roteiro, auditoria, metadados e RSS já estão completos.
- Produz MP3, roteiro em texto e feed RSS.
- Publica os arquivos pelo GitHub Pages.

O GitHub Actions é o agendador principal. Os minutos foram deslocados do início da
hora para reduzir atrasos e descartes em horários de pico. Os sinais por issue
`[scheduler] abertura` e `[scheduler] fechamento` permanecem como contingência
independente.

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
repositório. A geração usa Google Search no Gemini, registra uma ficha de auditoria e
faz novas tentativas para falhas transitórias. Se a chave estiver ausente, inválida ou
o conteúdo não passar nas travas factuais, o episódio não é publicado; a próxima
execução da janela tenta novamente. Não existe fallback editorial sem pesquisa.

## Comportamento dos sinais externos

- O sinal é aceito apenas quando criado pelo proprietário do repositório e o título é exato.
- Um sinal só é fechado quando o episódio já está completo ou foi publicado com sucesso.
- Se a geração falhar, o sinal fica aberto e recebe o link da execução com o diagnóstico.
