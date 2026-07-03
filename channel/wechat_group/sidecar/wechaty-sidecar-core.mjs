import xmlParser from 'fast-xml-parser'

const APP_MESSAGE_TYPE_REFER = 57

function stringValue(value = '') {
  if (value === null || value === undefined) return ''
  return String(value)
}

function emptyQuoteResult() {
  return { is_quote_self: false, quote: {} }
}

export function extractQuotedMessageFromRawPayload(rawPayload = {}, selfId = '') {
  const content = stringValue(rawPayload?.Content)
  if (!content.trim()) return emptyQuoteResult()
  try {
    const parsed = xmlParser.parse(content)
    const appmsg = parsed?.msg?.appmsg || {}
    if (Number(appmsg?.type) !== APP_MESSAGE_TYPE_REFER || !appmsg?.refermsg) {
      return emptyQuoteResult()
    }
    const refer = appmsg.refermsg
    const quote = {
      sender_id: stringValue(refer.fromusr),
      sender_name: stringValue(refer.displayname),
      message_id: stringValue(refer.svrid),
      type: stringValue(refer.type),
      content: stringValue(refer.content),
    }
    return {
      is_quote_self: Boolean(selfId && quote.sender_id === selfId),
      quote,
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

export async function resolveMentionTargets(room, mentionIds, findContact) {
  const mentions = await resolveMentionContacts(room, mentionIds, findContact)
  const targets = []
  for (const contact of mentions) {
    let name = ''
    try { name = await room.alias(contact) || '' } catch {}
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
