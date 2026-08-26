#!/usr/bin/env node

import { spawn } from 'node:child_process'
import { stat } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'

const VCS_EXCLUSIONS = ['.git', '.svn', '.hg', '.bzr', '.jj', '.sl']
const DEFAULT_HEAD_LIMIT = 250

function usage() {
  return `Usage:
  cc_rg_tool.mjs --pattern REGEX [--path PATH]
    [--glob GLOB] [--type TYPE]
    [--output-mode content|files_with_matches|count]
    [-A N] [-B N] [-C N] [--context N]
    [-n|--no-line-numbers] [-i] [--multiline]
    [--head-limit N] [--offset N] [--json] [--print-rg-command]
`
}

function parseArgs(argv) {
  const result = {
    outputMode: 'files_with_matches',
    lineNumbers: true,
    caseInsensitive: false,
    multiline: false,
    offset: 0,
    json: false,
    printRgCommand: false,
  }

  const nextValue = (index, option) => {
    if (index + 1 >= argv.length) throw new Error(`${option} requires a value`)
    return argv[index + 1]
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--pattern') result.pattern = nextValue(index++, arg)
    else if (arg === '--path') result.searchPath = nextValue(index++, arg)
    else if (arg === '--glob') result.glob = nextValue(index++, arg)
    else if (arg === '--type') result.type = nextValue(index++, arg)
    else if (arg === '--output-mode') result.outputMode = nextValue(index++, arg)
    else if (arg === '-A') result.afterContext = Number(nextValue(index++, arg))
    else if (arg === '-B') result.beforeContext = Number(nextValue(index++, arg))
    else if (arg === '-C') result.contextC = Number(nextValue(index++, arg))
    else if (arg === '--context') result.context = Number(nextValue(index++, arg))
    else if (arg === '-n' || arg === '--line-numbers') result.lineNumbers = true
    else if (arg === '--no-line-numbers') result.lineNumbers = false
    else if (arg === '-i' || arg === '--ignore-case') result.caseInsensitive = true
    else if (arg === '--multiline') result.multiline = true
    else if (arg === '--head-limit') result.headLimit = Number(nextValue(index++, arg))
    else if (arg === '--offset') result.offset = Number(nextValue(index++, arg))
    else if (arg === '--json') result.json = true
    else if (arg === '--print-rg-command') result.printRgCommand = true
    else if (arg === '--help' || arg === '-h') result.help = true
    else throw new Error(`Unknown argument: ${arg}`)
  }

  if (result.help) return result
  if (result.pattern === undefined) throw new Error('--pattern is required')
  if (!['content', 'files_with_matches', 'count'].includes(result.outputMode)) {
    throw new Error('--output-mode must be content, files_with_matches, or count')
  }
  for (const [name, value] of [
    ['-A', result.afterContext],
    ['-B', result.beforeContext],
    ['-C', result.contextC],
    ['--context', result.context],
    ['--head-limit', result.headLimit],
    ['--offset', result.offset],
  ]) {
    if (value !== undefined && (!Number.isInteger(value) || value < 0)) {
      throw new Error(`${name} must be an integer >= 0`)
    }
  }
  result.searchPath = path.resolve(result.searchPath ?? process.cwd())
  return result
}

function splitGlob(value) {
  if (!value) return []
  return value.split(/\s+/).flatMap(item =>
    item.includes('{') && item.includes('}')
      ? [item]
      : item.split(',').filter(Boolean),
  )
}

function shellQuote(value) {
  if (/^[A-Za-z0-9_./:=+-]+$/.test(value)) return value
  return `'${value.replaceAll("'", "'\\''")}'`
}

function buildRgArgs(input) {
  const args = ['--hidden', '--with-filename']
  for (const directory of VCS_EXCLUSIONS) args.push('--glob', `!${directory}`)
  args.push('--max-columns', '500')

  if (input.multiline) args.push('-U', '--multiline-dotall')
  if (input.caseInsensitive) args.push('-i')
  if (input.outputMode === 'files_with_matches') args.push('-l')
  else if (input.outputMode === 'count') args.push('-c')
  if (input.lineNumbers && input.outputMode === 'content') args.push('-n')

  if (input.outputMode === 'content') {
    if (input.context !== undefined) args.push('-C', String(input.context))
    else if (input.contextC !== undefined) args.push('-C', String(input.contextC))
    else {
      if (input.beforeContext !== undefined) args.push('-B', String(input.beforeContext))
      if (input.afterContext !== undefined) args.push('-A', String(input.afterContext))
    }
  }

  if (input.pattern.startsWith('-')) args.push('-e', input.pattern)
  else args.push(input.pattern)
  if (input.type) args.push('--type', input.type)
  for (const glob of splitGlob(input.glob)) args.push('--glob', glob)
  return args
}

function runRg(args, searchPath) {
  return new Promise((resolve, reject) => {
    const child = spawn('rg', [...args, searchPath], {
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: 20_000,
    })
    const stdout = []
    const stderr = []
    child.stdout.on('data', chunk => stdout.push(chunk))
    child.stderr.on('data', chunk => stderr.push(chunk))
    child.on('error', reject)
    child.on('close', code => {
      const errorText = Buffer.concat(stderr).toString('utf8')
      if (code !== 0 && code !== 1) {
        reject(new Error(`rg exited ${code}: ${errorText}`))
        return
      }
      resolve({
        code,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: errorText,
      })
    })
  })
}

function applyHeadLimit(items, limit, offset = 0) {
  if (limit === 0) {
    return { items: items.slice(offset), appliedLimit: undefined }
  }
  const effectiveLimit = limit ?? DEFAULT_HEAD_LIMIT
  const sliced = items.slice(offset, offset + effectiveLimit)
  return {
    items: sliced,
    appliedLimit: items.length - offset > effectiveLimit ? effectiveLimit : undefined,
  }
}

function relativePath(filePath) {
  if (!path.isAbsolute(filePath)) return filePath
  const relative = path.relative(process.cwd(), filePath)
  return relative || '.'
}

function relativeFirstPath(line, useLastColon = false) {
  const cwdPrefix = `${process.cwd()}${path.sep}`
  if (line.startsWith(cwdPrefix)) return line.slice(cwdPrefix.length)
  const colonIndex = useLastColon ? line.lastIndexOf(':') : line.indexOf(':')
  if (colonIndex <= 0) return line
  return `${relativePath(line.slice(0, colonIndex))}${line.slice(colonIndex)}`
}

async function grepTool(input) {
  const rgArgs = buildRgArgs(input)
  const execution = await runRg(rgArgs, input.searchPath)
  let lines = execution.stdout.split('\n')
  if (lines.at(-1) === '') lines.pop()

  if (input.outputMode === 'content') {
    const { items, appliedLimit } = applyHeadLimit(lines, input.headLimit, input.offset)
    const finalLines = items.map(line => relativeFirstPath(line))
    return {
      data: {
        mode: 'content',
        numFiles: 0,
        filenames: [],
        content: finalLines.join('\n'),
        numLines: finalLines.length,
        ...(appliedLimit !== undefined && { appliedLimit }),
        ...(input.offset > 0 && { appliedOffset: input.offset }),
      },
      rgArgs,
      exitCode: execution.code,
    }
  }

  if (input.outputMode === 'count') {
    const { items, appliedLimit } = applyHeadLimit(lines, input.headLimit, input.offset)
    const finalLines = items.map(line => relativeFirstPath(line, true))
    let numMatches = 0
    let numFiles = 0
    for (const line of finalLines) {
      const separator = line.lastIndexOf(':')
      const count = Number.parseInt(line.slice(separator + 1), 10)
      if (separator > 0 && Number.isFinite(count)) {
        numMatches += count
        numFiles += 1
      }
    }
    return {
      data: {
        mode: 'count',
        numFiles,
        filenames: [],
        content: finalLines.join('\n'),
        numMatches,
        ...(appliedLimit !== undefined && { appliedLimit }),
        ...(input.offset > 0 && { appliedOffset: input.offset }),
      },
      rgArgs,
      exitCode: execution.code,
    }
  }

  const stats = await Promise.allSettled(lines.map(file => stat(file)))
  const sorted = lines
    .map((file, index) => [
      file,
      stats[index].status === 'fulfilled' ? (stats[index].value.mtimeMs ?? 0) : 0,
    ])
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(item => item[0])
  const { items, appliedLimit } = applyHeadLimit(sorted, input.headLimit, input.offset)
  const filenames = items.map(relativePath)
  return {
    data: {
      mode: 'files_with_matches',
      filenames,
      numFiles: filenames.length,
      ...(appliedLimit !== undefined && { appliedLimit }),
      ...(input.offset > 0 && { appliedOffset: input.offset }),
    },
    rgArgs,
    exitCode: execution.code,
  }
}

function render(data) {
  if (data.mode === 'content') return data.content || 'No matches found'
  if (data.mode === 'count') {
    const content = data.content || 'No matches found'
    return `${content}\n\nFound ${data.numMatches} total occurrences across ${data.numFiles} files.`
  }
  if (data.numFiles === 0) return 'No files found'
  return `Found ${data.numFiles} files\n${data.filenames.join('\n')}`
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  if (args.help) {
    process.stdout.write(usage())
    return
  }
  const result = await grepTool(args)
  if (args.printRgCommand) {
    console.error(['rg', ...result.rgArgs, args.searchPath].map(shellQuote).join(' '))
  }
  if (args.json) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  else process.stdout.write(`${render(result.data)}\n`)
}

main().catch(error => {
  console.error(error.stack || error.message)
  process.exitCode = 1
})
