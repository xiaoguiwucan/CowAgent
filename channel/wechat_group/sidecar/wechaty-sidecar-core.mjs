import path from 'node:path'
import xmlParser from 'fast-xml-parser'

const APP_MESSAGE_TYPE_REFER = 57
const MESSAGE_TYPE_NAMES = {
  1: 'file',
  2: 'audio',
  5: 'sticker',
  6: 'image',
  7: 'text',
  15: 'video',
}
const DEFAULT_ALIAS_SYNC_COOLDOWN_MINUTES = 1
const aliasSyncCooldownByRoom = new Map()

function stringValue(value = '') {
  if (value === null || value === undefined) return ''
  return String(value)
}

function emptyQuoteResult() {
  return { is_quote_self: false, quote: {}, forward: {}, raw_app_type: '' }
}

function buildForwardPreview(appmsg = {}) {
  const type = Number(appmsg?.type || 0)
  const title = stringValue(appmsg?.title)
  const description = stringValue(appmsg?.des)
  const recordItem = stringValue(appmsg?.recorditem)
  const source = stringValue(appmsg?.sourcedisplayname || appmsg?.sourceusername || appmsg?.fromusername)
  const looksLikeForward = Boolean(
    recordItem ||
    type === 19 ||
    /聊天记录|转发/iu.test(title) ||
    /聊天记录|转发/iu.test(description),
  )
  if (!looksLikeForward) return {}
  const countMatches = [
    ...title.matchAll(/(\d+)\s*(条|段|个)/giu),
    ...description.matchAll(/(\d+)\s*(条|段|个)/giu),
  ]
  return {
    title: title.slice(0, 120),
    description: description.slice(0, 240),
    source: source.slice(0, 120),
    record_count_hint: countMatches.length ? Number(countMatches[0][1]) || 0 : 0,
    record_item: recordItem.slice(0, 2000),
  }
}

export function detectMessageMediaType(message) {
  let rawType = ''
  try {
    rawType = message?.type?.()
  } catch {
    rawType = ''
  }
  if (typeof rawType === 'number') {
    return MESSAGE_TYPE_NAMES[rawType] || 'text'
  }
  const normalized = String(rawType || '').trim().toLowerCase()
  if (normalized.includes('emoticon') || normalized.includes('sticker')) return 'sticker'
  if (normalized.includes('image')) return 'image'
  if (normalized.includes('audio') || normalized.includes('voice')) return 'audio'
  if (normalized.includes('video')) return 'video'
  if (normalized.includes('attachment') || normalized.includes('file')) return 'file'
  return 'text'
}

export function sanitizeMediaFilePart(value = '') {
  const cleaned = String(value || '')
    .replace(/[\\/]+/g, '_')
    .replace(/\.\.+/g, '')
    .replace(/[^\w@.-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 120)
  return cleaned || 'unknown'
}

function mediaExtension(fileName = '', mediaType = '') {
  const ext = path.extname(String(fileName || '')).toLowerCase().replace('.', '')
  if (ext) return ext
  if (mediaType === 'sticker') return 'gif'
  if (mediaType === 'image') return 'jpg'
  if (mediaType === 'audio') return 'mp3'
  if (mediaType === 'video') return 'mp4'
  return 'dat'
}

export function buildMediaFilePath(mediaDir, roomId, messageId, fileName = '', mediaType = 'image') {
  const dir = path.join(String(mediaDir || ''), sanitizeMediaFilePart(roomId))
  const baseName = sanitizeMediaFilePart(messageId)
  const ext = mediaExtension(fileName, mediaType)
  return path.join(dir, `${baseName}.${ext}`)
}

export function extractQuotedMessageFromRawPayload(rawPayload = {}, selfId = '') {
  const content = stringValue(rawPayload?.Content)
  if (!content.trim()) return emptyQuoteResult()
  try {
    const parsed = xmlParser.parse(content)
    const appmsg = parsed?.msg?.appmsg || {}
    const appType = stringValue(appmsg?.type)
    let quote = {}
    let isQuoteSelf = false
    if (Number(appmsg?.type) === APP_MESSAGE_TYPE_REFER && appmsg?.refermsg) {
      const refer = appmsg.refermsg
      quote = {
        sender_id: stringValue(refer.fromusr),
        sender_name: stringValue(refer.displayname),
        message_id: stringValue(refer.svrid),
        type: stringValue(refer.type),
        content: stringValue(refer.content),
      }
      isQuoteSelf = Boolean(selfId && quote.sender_id === selfId)
    }
    return {
      is_quote_self: isQuoteSelf,
      quote,
      forward: buildForwardPreview(appmsg),
      raw_app_type: appType,
    }
  } catch {
    return emptyQuoteResult()
  }
}

export async function findRoomById(bot, roomId) {
  if (!bot) throw new Error('bot not started')
  const room = await bot.Room.find({ id: roomId })
  return room
}

export async function findContactById(bot, contactId) {
  if (!bot) throw new Error('bot not started')
  return bot.Contact.find({ id: contactId })
}

export async function resolveMentionContacts(room, mentionIds, findContact) {
  const mentions = []
  for (const contactId of mentionIds || []) {
    const wanted = String(contactId || '').trim()
    if (!wanted) continue
    let contact = null
    try {
      const members = await room.memberAll?.()
      contact = (members || []).find(item => String(item?.id || '').trim() === wanted) || null
    } catch {}
    if (contact) {
      mentions.push(contact)
      continue
    }
    if (!contact) {
      contact = await findContact(wanted).catch(() => null)
    }
    if (!contact) continue
    const inRoom = await room.has?.(contact).catch(() => false)
    if (inRoom) mentions.push(contact)
  }
  return mentions
}

function cleanMentionName(value = '') {
  return String(value || '')
    .replace(/<br\s*\/?>/giu, ' ')
    .replace(/<[^>]+>/gu, '')
    .replace(/&nbsp;/giu, ' ')
    .replace(/&amp;/giu, '&')
    .replace(/&lt;/giu, '<')
    .replace(/&gt;/giu, '>')
    .replace(/^[@＠]+/u, '')
    .replace(/[\r\n]+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
    .slice(0, 40)
}

function stripLeadingMentionText(text = '') {
  let value = String(text || '').trim()
  for (let i = 0; i < 5; i++) {
    const next = value.replace(/^[@＠][^\s\u2005\u2006\u2007\u2008\u2009\u200a，,：:、]{0,40}[\s\u2005\u2006\u2007\u2008\u2009\u200a，,：:、]*/u, '').trim()
    if (next === value) break
    value = next
  }
  return value || String(text || '').trim()
}

export function buildManualMentionText(text = '', targets = []) {
  const names = targets.map(item => cleanMentionName(item?.name || '')).filter(Boolean)
  if (!names.length) return String(text || '')
  return `${names.map(name => `@${name}`).join('\u2005')}\u2005${stripLeadingMentionText(text)}`
}

function escapeMsgSourceXml(value = '') {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function makeClientMsgId() {
  return Math.ceil(Date.now() * 1000)
}

function buildAtUserList(targets = []) {
  const seen = new Set()
  const ids = []
  for (const target of targets || []) {
    const id = String(target?.id || target?.contact?.id || '').trim()
    if (!id || id.startsWith('@@') || seen.has(id)) continue
    seen.add(id)
    ids.push(id)
    if (ids.length >= 20) break
  }
  return ids
}

function buildMsgSourceXml(targetIds = []) {
  const ids = targetIds.map(id => String(id || '').trim()).filter(Boolean)
  if (!ids.length) return ''
  return `<msgsource><atuserlist>${ids.map(escapeMsgSourceXml).join(',')}</atuserlist></msgsource>`
}

function normalizeAliasSyncCooldownMinutes(value) {
  const minutes = Number(value)
  if (!Number.isFinite(minutes) || minutes < 1) return DEFAULT_ALIAS_SYNC_COOLDOWN_MINUTES
  return minutes
}

function shouldRefreshRoomAlias(roomId, cooldownMinutes, cooldownStore, nowMs) {
  const normalizedRoomId = String(roomId || '').trim()
  if (!normalizedRoomId) return false
  const store = cooldownStore || aliasSyncCooldownByRoom
  const currentNowMs = Number(nowMs)
  const safeNowMs = Number.isFinite(currentNowMs) ? currentNowMs : Date.now()
  const cooldownMs = normalizeAliasSyncCooldownMinutes(cooldownMinutes) * 60 * 1000
  const hasLastSync = store.has(normalizedRoomId)
  const lastSyncAt = hasLastSync ? Number(store.get(normalizedRoomId)) : 0
  if (hasLastSync && Number.isFinite(lastSyncAt) && safeNowMs - lastSyncAt < cooldownMs) {
    return false
  }
  store.set(normalizedRoomId, safeNowMs)
  return true
}

export async function resolveMentionTargets(room, mentionIds, findContact, options = {}) {
  const mentions = await resolveMentionContacts(room, mentionIds, findContact)
  const targets = []
  let aliasRefreshAttempted = false
  const cooldownMinutes = options.aliasSyncCooldownMinutes
  const cooldownStore = options.aliasSyncCooldownStore
  const nowMs = options.nowMs
  for (const contact of mentions) {
    let name = ''
    try { name = await room.alias(contact) || '' } catch {}
    if (
      !name &&
      !aliasRefreshAttempted &&
      room?.sync &&
      shouldRefreshRoomAlias(room?.id, cooldownMinutes, cooldownStore, nowMs)
    ) {
      aliasRefreshAttempted = true
      try {
        await room.sync()
        name = await room.alias(contact) || ''
      } catch {}
    }
    if (!name) {
      try { name = contact.name() || '' } catch {}
    }
    targets.push({ id: contact.id, contact, name: cleanMentionName(name) })
  }
  return targets
}

export function getWechat4uRuntime(bot) {
  return bot?.puppet?.wechat4u || bot?.puppet?.wechat4uBridge?.wechat4u || null
}

export function isWechat4uBot(bot) {
  const puppetName = String(bot?.puppet?.constructor?.name || bot?.puppet?.name || '').trim()
  return /wechat4u/iu.test(puppetName) || !!getWechat4uRuntime(bot)
}

export async function sendWechat4uRawTextWithMsgSource(wechat4u, room, text, mentionTargets = []) {
  const roomId = String(room?.id || '').trim()
  if (!wechat4u || !roomId) throw new Error('wechat4u runtime or room id missing')
  if (!wechat4u.request || !wechat4u.CONF || !wechat4u.PROP || !wechat4u.user || !wechat4u.getBaseRequest) {
    throw new Error('wechat4u internals unavailable')
  }
  const targetIds = buildAtUserList(mentionTargets)
  if (!targetIds.length) throw new Error('mention target id missing')
  const msgSource = buildMsgSourceXml(targetIds)
  const content = buildManualMentionText(text, mentionTargets)
  const clientMsgId = makeClientMsgId()
  const response = await wechat4u.request({
    method: 'POST',
    url: wechat4u.CONF.API_webwxsendmsg,
    params: {
      pass_ticket: wechat4u.PROP.passTicket,
      lang: 'zh_CN',
    },
    data: {
      BaseRequest: wechat4u.getBaseRequest(),
      Scene: 0,
      Msg: {
        Type: wechat4u.CONF.MSGTYPE_TEXT,
        Content: content,
        FromUserName: wechat4u.user.UserName || wechat4u.user.userName || wechat4u.user['UserName'],
        ToUserName: roomId,
        LocalID: clientMsgId,
        ClientMsgId: clientMsgId,
        MsgSource: msgSource,
      },
    },
  })
  const data = response?.data || {}
  const ret = Number(data?.BaseResponse?.Ret)
  if (ret !== 0) {
    const errMsg = data?.BaseResponse?.ErrMsg || JSON.stringify(data?.BaseResponse || data)
    throw new Error(`webwxsendmsg ret=${data?.BaseResponse?.Ret} ${errMsg}`)
  }
  return { ok: true, roomId, targetIds, msgSource, content, response: data }
}

export async function sendText(command, deps) {
  const room = await deps.findRoom(command.room_id)
  if (!room) throw new Error(`room not found: ${command.room_id}`)
  const mentionTargets = await resolveMentionTargets(
    room,
    command.mention_ids || [],
    deps.findContact,
    {
      aliasSyncCooldownMinutes: command.alias_sync_cooldown_minutes,
      aliasSyncCooldownStore: deps.aliasSyncCooldownStore,
      nowMs: deps.nowMs?.(),
    },
  )
  const wechat4u = deps.getWechat4u?.()
  const useVisibleMentionText = mentionTargets.length && (deps.isWechat4u?.() || wechat4u)
  if (mentionTargets.length && wechat4u) {
    try {
      await sendWechat4uRawTextWithMsgSource(wechat4u, room, command.text, mentionTargets)
    } catch {
      await room.say(buildManualMentionText(command.text, mentionTargets))
    }
  } else if (useVisibleMentionText) {
    await room.say(buildManualMentionText(command.text, mentionTargets))
  } else if (mentionTargets.length) {
    const contacts = mentionTargets.map(item => item.contact).filter(Boolean)
    const manualText = buildManualMentionText(command.text, mentionTargets)
    try {
      await room.say(command.text, ...contacts)
    } catch {
      await room.say(manualText || command.text)
    }
  } else {
    await room.say(command.text)
  }
  deps.emit('send_result', { ok: true, command: 'send_text', room_id: command.room_id })
}
