#!/usr/bin/env node

import { createHash } from 'node:crypto'
import {
  closeSync,
  copyFileSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  statSync,
  writeSync,
} from 'node:fs'
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath, pathToFileURL } from 'node:url'

const readFileState = new Map()

function parseArgs(argv) {
  const result = {
    bundle: path.dirname(fileURLToPath(import.meta.url)),
    cases: [],
    iterations: 1,
    warmup: 0,
    list: false,
    output: undefined,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--bundle') result.bundle = argv[++i]
    else if (arg === '--case') result.cases.push(argv[++i])
    else if (arg === '--iterations') result.iterations = Number(argv[++i])
    else if (arg === '--warmup') result.warmup = Number(argv[++i])
    else if (arg === '--output') result.output = argv[++i]
    else if (arg === '--list') result.list = true
    else if (arg === '--help' || arg === '-h') result.help = true
    else throw new Error(`Unknown argument: ${arg}`)
  }
  if (!Number.isInteger(result.iterations) || result.iterations < 1) {
    throw new Error('--iterations must be an integer >= 1')
  }
  if (!Number.isInteger(result.warmup) || result.warmup < 0) {
    throw new Error('--warmup must be an integer >= 0')
  }
  result.bundle = path.resolve(result.bundle)
  return result
}

function usage() {
  return `Usage:
  node cc_tool_microbench.mjs --bundle BUNDLE --list
  node cc_tool_microbench.mjs --bundle BUNDLE [--case ID ...] [--warmup N] [--iterations N] [--output DIR]
`
}

function sha256(content) {
  return createHash('sha256').update(content).digest('hex')
}

function timestamp() {
  const now = new Date()
  const pad = value => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

function csvEscape(value) {
  const text = String(value ?? '')
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function normalizeLines(text) {
  return text.replaceAll('\r\n', '\n').split('\n')
}

function renderNumbered(content, startLine) {
  const lines = normalizeLines(content)
  if (lines.at(-1) === '') lines.pop()
  return lines.map((line, index) => `${String(startLine + index).padStart(6)}\t${line}`).join('\n')
}

export async function readTool(filePath, offset = 1, limit = undefined) {
  const fullPath = path.resolve(filePath)
  const prior = readFileState.get(fullPath)
  if (prior && prior.offset === offset && prior.limit === limit) {
    const metadata = await stat(fullPath)
    if (Math.floor(metadata.mtimeMs) === prior.timestamp) {
      return { rendered: 'File unchanged since last read.', dedup: true, content: prior.content }
    }
  }

  const [raw, metadata] = await Promise.all([readFile(fullPath, 'utf8'), stat(fullPath)])
  const allLines = normalizeLines(raw)
  if (allLines.at(-1) === '') allLines.pop()
  const start = offset === 0 ? 0 : offset - 1
  const selected = allLines.slice(start, limit === undefined ? undefined : start + limit)
  const content = selected.join('\n') + (selected.length > 0 ? '\n' : '')
  readFileState.set(fullPath, {
    content,
    timestamp: Math.floor(metadata.mtimeMs),
    offset,
    limit,
    isPartialView: limit !== undefined || start !== 0,
  })
  return {
    rendered: renderNumbered(content, offset),
    dedup: false,
    content,
    totalLines: allLines.length,
  }
}

function writeTextContentAndFlush(filePath, content) {
  const descriptor = openSync(filePath, 'w')
  try {
    const buffer = Buffer.from(content, 'utf8')
    let offset = 0
    while (offset < buffer.length) {
      offset += writeSync(descriptor, buffer, offset, buffer.length - offset, null)
    }
    fsyncSync(descriptor)
  } finally {
    closeSync(descriptor)
  }
}

export function fullReadState(filePath) {
  const content = readFileSync(filePath, 'utf8').replaceAll('\r\n', '\n')
  const metadata = statSync(filePath)
  readFileState.set(path.resolve(filePath), {
    content,
    timestamp: Math.floor(metadata.mtimeMs),
    offset: undefined,
    limit: undefined,
    isPartialView: false,
  })
  return content
}

export function writeTool(filePath, content) {
  const fullPath = path.resolve(filePath)
  mkdirSync(path.dirname(fullPath), { recursive: true })
  if (existsSync(fullPath)) {
    const previous = readFileState.get(fullPath)
    if (!previous || previous.isPartialView) throw new Error('File has not been read yet')
    const current = readFileSync(fullPath, 'utf8').replaceAll('\r\n', '\n')
    const currentMtime = Math.floor(statSync(fullPath).mtimeMs)
    if (currentMtime > previous.timestamp && current !== previous.content) {
      throw new Error('File has been modified since read')
    }
  }
  writeTextContentAndFlush(fullPath, content)
  readFileState.set(fullPath, {
    content,
    timestamp: Math.floor(statSync(fullPath).mtimeMs),
    offset: undefined,
    limit: undefined,
    isPartialView: false,
  })
  return { rendered: `File written successfully: ${fullPath}`, content }
}

function literalMatchCount(content, needle) {
  if (needle === '') return content === '' ? 1 : 0
  let count = 0
  let position = 0
  while ((position = content.indexOf(needle, position)) !== -1) {
    count += 1
    position += needle.length
  }
  return count
}

function makePatchAndSnippet(original, updated, oldString, newString) {
  const before = normalizeLines(original)
  const oldStartOffset = original.indexOf(oldString)
  const startLine = original.slice(0, oldStartOffset).split('\n').length
  const removed = normalizeLines(oldString)
  const added = normalizeLines(newString)
  const contextStart = Math.max(0, startLine - 5)
  const contextEnd = Math.min(normalizeLines(updated).length, startLine + added.length + 4)
  const updatedLines = normalizeLines(updated)
  const snippet = updatedLines
    .slice(contextStart, contextEnd)
    .map((line, index) => `${String(contextStart + index + 1).padStart(6)}\t${line}`)
    .join('\n')
  const patch = [
    `@@ -${startLine},${removed.length} +${startLine},${added.length} @@`,
    ...removed.map(line => `-${line}`),
    ...added.map(line => `+${line}`),
  ].join('\n')
  return { patch, snippet, sourceLines: before.length }
}

export function editTool(filePath, oldString, newString, replaceAll = false) {
  const fullPath = path.resolve(filePath)
  mkdirSync(path.dirname(fullPath), { recursive: true })
  const original = readFileSync(fullPath, 'utf8').replaceAll('\r\n', '\n')
  const metadata = statSync(fullPath)
  const previous = readFileState.get(fullPath)
  if (!previous || previous.isPartialView) throw new Error('File has not been fully read yet')
  if (Math.floor(metadata.mtimeMs) > previous.timestamp && original !== previous.content) {
    throw new Error('File has been modified since read')
  }
  const matches = literalMatchCount(original, oldString)
  if (matches === 0) throw new Error('String to replace not found in file')
  if (matches > 1 && !replaceAll) throw new Error(`Found ${matches} matches while replace_all is false`)
  const updated = replaceAll ? original.split(oldString).join(newString) : original.replace(oldString, newString)
  const display = makePatchAndSnippet(original, updated, oldString, newString)
  writeTextContentAndFlush(fullPath, updated)
  readFileState.set(fullPath, {
    content: updated,
    timestamp: Math.floor(statSync(fullPath).mtimeMs),
    offset: undefined,
    limit: undefined,
    isPartialView: false,
  })
  return { rendered: display.snippet, content: updated, patch: display.patch, matches }
}

function validate(caseInfo, result, targetPath) {
  if (caseInfo.tool === 'Read') {
    return sha256(readFileSync(path.resolve(targetPath))) === caseInfo.expected_source_sha256 && result.content.length > 0
  }
  if (caseInfo.tool === 'Write' || caseInfo.tool === 'Edit') {
    return sha256(readFileSync(targetPath)) === caseInfo.expected_sha256
  }
  return true
}

function prepare(caseInfo, bundle, workRoot, sequence) {
  if (caseInfo.tool === 'Write') {
    return { targetPath: path.join(workRoot, caseInfo.id, `run_${sequence}`, 'nested', 'reproduce.py') }
  }
  if (caseInfo.tool === 'Edit') {
    const source = path.resolve(bundle, caseInfo.fixture)
    const targetPath = path.join(workRoot, caseInfo.id, `run_${sequence}`, 'formsets.py')
    mkdirSync(path.dirname(targetPath), { recursive: true })
    copyFileSync(source, targetPath)
    fullReadState(targetPath)
    return { targetPath }
  }
  if (caseInfo.fixture) return { targetPath: path.resolve(bundle, caseInfo.fixture) }
  return { targetPath: undefined }
}

async function execute(caseInfo, bundle, prepared) {
  if (caseInfo.tool === 'Read') return readTool(prepared.targetPath, caseInfo.offset, caseInfo.limit ?? undefined)
  if (caseInfo.tool === 'Write') return writeTool(prepared.targetPath, caseInfo.content)
  if (caseInfo.tool === 'Edit') {
    return editTool(prepared.targetPath, caseInfo.old_string, caseInfo.new_string, caseInfo.replace_all)
  }
  throw new Error(`Unsupported tool: ${caseInfo.tool}`)
}

async function timedRun(caseInfo, bundle, workRoot, sequence) {
  const prepared = prepare(caseInfo, bundle, workRoot, sequence)
  if (caseInfo.tool === 'Read') readFileState.delete(path.resolve(prepared.targetPath))
  const cpuBefore = process.cpuUsage()
  const start = process.hrtime.bigint()
  const result = await execute(caseInfo, bundle, prepared)
  const wallNs = process.hrtime.bigint() - start
  const cpu = process.cpuUsage(cpuBefore)
  const valid = validate(caseInfo, result, prepared.targetPath)
  return {
    result,
    row: {
      case_id: caseInfo.id,
      tool: caseInfo.tool,
      iteration: sequence,
      wall_ns: Number(wallNs),
      wall_ms: Number(wallNs) / 1_000_000,
      user_cpu_us: cpu.user,
      system_cpu_us: cpu.system,
      output_bytes: Buffer.byteLength(result.rendered ?? '', 'utf8'),
      valid,
      target_path: prepared.targetPath ?? '',
    },
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  if (args.help) {
    process.stdout.write(usage())
    return
  }
  const manifest = JSON.parse(await readFile(path.join(args.bundle, 'manifest.json'), 'utf8'))
  let cases = manifest.cases
  if (args.list) {
    for (const item of cases) console.log(`${item.id}\t${item.tool}\t${item.description}`)
    return
  }
  if (args.cases.length > 0) {
    const wanted = new Set(args.cases)
    cases = cases.filter(item => wanted.has(item.id))
    const missing = [...wanted].filter(id => !cases.some(item => item.id === id))
    if (missing.length > 0) throw new Error(`Unknown cases: ${missing.join(', ')}`)
  }

  const output = path.resolve(args.output ?? path.join(args.bundle, 'results', timestamp()))
  if (existsSync(output)) throw new Error(`Output already exists: ${output}`)
  await mkdir(output, { recursive: true })
  const workRoot = path.join(output, 'work')
  const rows = []

  for (const caseInfo of cases) {
    for (let warmup = 1; warmup <= args.warmup; warmup += 1) {
      await timedRun(caseInfo, args.bundle, workRoot, `warmup_${warmup}`)
    }
    for (let iteration = 1; iteration <= args.iterations; iteration += 1) {
      const { result, row } = await timedRun(caseInfo, args.bundle, workRoot, iteration)
      rows.push(row)
      if (iteration === 1) {
        const artifactDir = path.join(output, 'artifacts', caseInfo.id)
        await mkdir(artifactDir, { recursive: true })
        await writeFile(path.join(artifactDir, 'output.txt'), `${result.rendered ?? ''}\n`, 'utf8')
        await writeFile(path.join(artifactDir, 'result.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
      }
      console.log(`${caseInfo.id} iteration=${iteration} wall=${row.wall_ms.toFixed(3)}ms valid=${row.valid}`)
    }
  }

  const fields = Object.keys(rows[0])
  const csv = [fields.join(','), ...rows.map(row => fields.map(field => csvEscape(row[field])).join(','))].join('\n')
  await writeFile(path.join(output, 'results.csv'), `${csv}\n`, 'utf8')
  await writeFile(path.join(output, 'results.json'), `${JSON.stringify(rows, null, 2)}\n`, 'utf8')
  const failures = rows.filter(row => !row.valid)
  console.log(`OUTPUT=${output}`)
  console.log(`RUNS=${rows.length} FAILURES=${failures.length}`)
  if (failures.length > 0) process.exitCode = 1
}

const isEntryPoint =
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href

if (isEntryPoint) {
  main().catch(error => {
    console.error(error.stack || error.message)
    process.exitCode = 1
  })
}
