export const meta = {
  name: 'vremya-cycle',
  description: 'Полный цикл: поиск цитат Шри Чинмоя о времени → отбор → сценарий → генерация видео → upload (4 агента)',
  phases: [
    { title: 'Research', detail: 'Агент 1: ищет все упоминания времени на srichinmoylibrary.com (6 запросов)' },
    { title: 'Curate+Script', detail: 'Агент 2: отбирает лучшую цитату + пишет сценарий ролика' },
    { title: 'Produce', detail: 'Агент 3: генерирует голос + изображения + монтирует видео' },
    { title: 'Upload', detail: 'Агент 4: загружает на YouTube с планированием' },
  ],
}

const SERIES_SLUG = 'taina-vremeni-shorts'
const SERIES_TITLE = 'Тайна времени'
const START_DATE = args?.startDate ?? '2026-09-18'

// ── Pipeline: 4 agents sequentially ─────────────────────────────────────

const result = await pipeline(
  // Input: config
  [{ count: args?.count ?? 1, skipUpload: args?.skipUpload ?? false }],

  // Stage 1: Research (Agent 1)
  async (config) => {
    phase('Research')
    log('Агент 1: Ищу цитаты о времени на srichinmoylibrary.com...')

    const searchTerms = ['время', 'секунда', 'мгновение', 'момент', 'миг', 'вечность']
    const allQuotes = []

    for (const term of searchTerms) {
      const result = await agent(
        `Найди ВСЕ упоминания слова «${term}» в контексте ВРЕМЕНИ (секунды, мгновения, моменты) ` +
        `на сайте https://ru.srichinmoylibrary.com\n\n` +
        `Алгоритм:\n` +
        `1. Открой https://ru.srichinmoylibrary.com/search?q=${encodeURIComponent(term)} через WebFetch\n` +
        `2. Если поиск не работает, попробуй главную страницу и навигацию по книгам\n` +
        `3. Извлеки цитаты, где «${term}» относится ко времени (не к бытовому «во сколько встреча» ` +
        `и не к «вечности» как чисто духовной парадигме)\n` +
        `4. Цель: необычные, мистические, парадоксальные высказывания о природе времени\n\n` +
        `Примеры того, что НУЖНО:\n` +
        `— «В одну секунду можно обрести Бессмертие» (время как шанс)\n` +
        `— «Вечность — это не бесконечное время, а глубина одного мгновения» (парадокс)\n` +
        `— «Каждое мгновение — это новая вечность» (мистерия)\n\n` +
        `Примеры того, что НЕ НУЖНО:\n` +
        `— «Я прихожу в 5 часов» (бытовое)\n` +
        `— «Вечность — это Бог» (чисто духовная парадигма без привязки ко времени)\n\n` +
        `Верни цитаты в формате JSON:\n` +
        `{"quotes": [{"text": "...", "url": "...", "book": "..."}]}`,
        { label: `research:${term}` }
      )

      try {
        // Extract JSON from markdown code blocks or raw text
        let jsonStr = result
        const codeBlockMatch = result.match(/```(?:json)?\s*([\s\S]*?)```/)
        if (codeBlockMatch) jsonStr = codeBlockMatch[1]
        // Try to find JSON object in the text
        const jsonMatch = jsonStr.match(/\{[\s\S]*"quotes"[\s\S]*\}/)
        if (jsonMatch) jsonStr = jsonMatch[0]
        const parsed = JSON.parse(jsonStr)
        if (parsed.quotes) {
          allQuotes.push(...parsed.quotes.map(q => ({ ...q, search_term: term })))
          log(`  «${term}»: +${parsed.quotes.length} цитат`)
        }
      } catch (e) {
        log(`  Не удалось распарсить результат для «${term}»: ${e.message}`)
      }
    }

    log(`Найдено ${allQuotes.length} цитат`)
    return { ...config, allQuotes }
  },

  // Stage 2: Curate + Script (Agent 2)
  async (ctx) => {
    phase('Curate+Script')
    log(`Агент 2: Отбираю лучшую цитату из ${ctx.allQuotes.length} и пишу сценарий...`)

    const result = await agent(
      `Ты — куратор и сценарист серии роликов «${SERIES_TITLE}» о тайне времени в учениях Шри Чинмоя.\n\n` +
      `ЗАДАЧА 1: Отбери ОДНУ лучшую цитату из списка ниже по критериям:\n` +
      `— Мистерия / парадокс (переворачивает восприятие времени)\n` +
      `— Необычность (неочевидная связь времени с чем-то конкретным)\n` +
      `— Новый ракурс (не «тигр желаний», не «спираль»)\n` +
      `— Визуальность (рождает яркий кадр)\n` +
      `— Краткость (1-3 предложения)\n\n` +
      `ЗАДАЧА 2: Напиши сценарий для ролика (60 сек, 9:16) на основе выбранной цитаты.\n\n` +
      `ФОРМАТ СЦЕНАРИЯ:\n` +
      `— hook: 1-2 предложения, цепляют с первой секунды (факт или парадокс, не вопрос)\n` +
      `— vo: 100-140 слов, рассказывают историю через конкретный образ, язык простой, без пафоса\n` +
      `— ending: 1-2 предложения, клифхэнгер или мощная финальная мысль\n` +
      `— images: 4 промпта на английском для генерации изображений (9:16 vertical). ` +
      `Каждый промпт — конкретная визуальная сцена. Стиль: «authentic archival photograph, ` +
      `35mm film grain, warm golden light». Duration fractions в сумме ~1.0.\n` +
      `— aphorism: афоризм для peel-эффекта (2-4 строки + source + url)\n\n` +
      `СТИЛЬ (по образцу серии «Последний вулкан»):\n` +
      `— Конкретика: числа, имена, даты — если уместны\n` +
      `— Метафоры из физического мира (горы, реки, мосты, часы)\n` +
      `— Духовная параллель — только если органична\n` +
      `— Каждое предложение несёт информацию\n\n` +
      `slug: придумай kebab-case slug на английском.\n\n` +
      `Верни результат в формате JSON:\n` +
      `{\n` +
      `  "selected_quote": {"text": "...", "url": "...", "book": "..."},\n` +
      `  "script": {\n` +
      `    "slug": "...",\n` +
      `    "hook": "...",\n` +
      `    "vo": "...",\n` +
      `    "ending": "...",\n` +
      `    "images": [["prompt", fraction], ...],\n` +
      `    "aphorism": {"text": "...", "source": "...", "url": "..."}\n` +
      `  }\n` +
      `}\n\n` +
      `Цитаты для отбора:\n${JSON.stringify(ctx.allQuotes, null, 2)}`,
      { label: 'curate+script' }
    )

    try {
      const parsed = JSON.parse(result)
      log(`Отобрана цитата: «${parsed.selected_quote.text.slice(0, 60)}...»`)
      log(`Сценарий написан: ${parsed.script.slug}`)
      return { ...ctx, script: parsed.script, selectedQuote: parsed.selected_quote }
    } catch (e) {
      log('Ошибка парсинга сценария')
      return { ...ctx, script: null }
    }
  },

  // Stage 3: Produce (Agent 3)
  async (ctx) => {
    if (!ctx.script) {
      log('Нет сценария, пропускаю генерацию')
      return { ...ctx, outputFile: null }
    }

    phase('Produce')
    log('Агент 3: Генерирую видео (голос + изображения + монтаж)...')

    const scriptsDir = `narrated-shorts/${SERIES_SLUG}`
    const specFile = `${scriptsDir}/scripts-build-1.json`

    const spec = [{
      id: 1,
      slug: ctx.script.slug,
      hook: ctx.script.hook,
      vo: ctx.script.vo,
      ending: ctx.script.ending,
      images: ctx.script.images,
      voice: {
        voice_id: 'Nikolai',
        model: 'inworld-tts-1.5-max',
        temperature: 1.1,
        speaking_rate: 1.0,
      },
      image_provider: 'alibaba',
      image_model: 'wan2.7-image',
      image_style: ', authentic archival photograph, 35mm film grain, warm golden light, ' +
        'slight atmospheric haze, contemplative mood, full-bleed image filling the whole frame',
      image_negative: 'modern digital render, CGI, 3d render, HDR, oversaturated colours, ' +
        'drone shot, text, watermark, logo, letterbox, white border, recognisable face, portrait likeness',
      aphorism: ctx.script.aphorism,
    }]

    await agent(
      `Выполни шаги для генерации видео:\n` +
      `1. mkdir -p narrated-shorts/${SERIES_SLUG}/output\n` +
      `2. Запиши файл ${specFile}:\n${JSON.stringify(spec, null, 2)}\n` +
      `3. Запусти: export PATH="/Users/Awaikened/bin:$PATH" && python3 tools/build_narrated_short.py --spec-file ${specFile} --id 1\n` +
      `4. Проверь, что файл narrated-shorts/${SERIES_SLUG}/output/short-01-*.mp4 создан\n` +
      `5. Верни путь к файлу`,
      { label: 'produce' }
    )

    const outputFile = `narrated-shorts/${SERIES_SLUG}/output/short-01-${ctx.script.slug}.mp4`
    log(`Видео сгенерировано: ${outputFile}`)
    return { ...ctx, outputFile }
  },

  // Stage 4: Upload (Agent 4)
  async (ctx) => {
    if (ctx.skipUpload || !ctx.outputFile) {
      log('Upload пропущен')
      return { ...ctx, uploadResult: 'skipped' }
    }

    phase('Upload')
    log('Агент 4: Загружаю на YouTube...')

    await agent(
      `Загрузи эпизод серии «${SERIES_TITLE}» на YouTube.\n\n` +
      `Шаги:\n` +
      `1. Обнови tools/upload_youtube.py — добавь в TITLES, DESCRIPTIONS, TAGS_LIST новый эпизод\n` +
      `2. Запусти: python3 tools/upload_youtube.py --upload 1\n` +
      `3. Дата публикации: ${START_DATE}, 10:00 Алма-Ата (04:00 UTC)\n\n` +
      `Данные эпизода:\n` +
      `— slug: ${ctx.script.slug}\n` +
      `— hook: ${ctx.script.hook}\n` +
      `— aphorism: ${ctx.script.aphorism.text}\n\n` +
      `Верни URL загруженного видео.`,
      { label: 'upload' }
    )

    log('Загрузка завершена')
    return { ...ctx, uploadResult: 'done' }
  }
)

// ── Summary ──────────────────────────────────────────────────────────────

log(`\n✅ Цикл завершён!`)
log(`   Найдено цитат: ${result[0]?.allQuotes?.length ?? 0}`)
log(`   Отобрано: ${result[0]?.selectedQuote ? '1' : '0'}`)
log(`   Сценарий: ${result[0]?.script ? 'готов' : 'нет'}`)
log(`   Видео: ${result[0]?.outputFile ?? 'не сгенерировано'}`)
log(`   Upload: ${result[0]?.uploadResult ?? 'не выполнен'}`)

return result[0]
