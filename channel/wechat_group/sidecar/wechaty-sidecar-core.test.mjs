import test from 'node:test'
import assert from 'node:assert/strict'

import { extractQuotedMessageFromRawPayload, sendText, sendWechat4uRawTextWithMsgSource } from './wechaty-sidecar-core.mjs'

function buildReferMsgContent({ fromusr = '@bot', displayname = 'CowBot', content = 'previous answer', title = 'current reply' } = {}) {
  return `<msg><appmsg><title>${title}</title><des></des><type>57</type><url></url><appattach></appattach><thumburl></thumburl><md5></md5><refermsg><type>1</type><svrid>123456</svrid><fromusr>${fromusr}</fromusr><chatusr>@@room</chatusr><displayname>${displayname}</displayname><content>${content}</content></refermsg></appmsg><fromusername>@@room</fromusername><appinfo><appname></appname></appinfo></msg>`
}

test('extractQuotedMessageFromRawPayload marks quote self when refermsg sender is current bot', () => {
  const result = extractQuotedMessageFromRawPayload({
    MsgType: 49,
    Content: buildReferMsgContent({ fromusr: '@bot', displayname: 'CowBot', content: 'hello from bot' }),
  }, '@bot')

  assert.equal(result.is_quote_self, true)
  assert.deepEqual(result.quote, {
    sender_id: '@bot',
    sender_name: 'CowBot',
    message_id: '123456',
    type: '1',
    content: 'hello from bot',
  })
})

test('extractQuotedMessageFromRawPayload does not mark quote self for other sender', () => {
  const result = extractQuotedMessageFromRawPayload({
    MsgType: 49,
    Content: buildReferMsgContent({ fromusr: '@alice', displayname: 'Alice', content: 'hello from alice' }),
  }, '@bot')

  assert.equal(result.is_quote_self, false)
  assert.equal(result.quote.sender_id, '@alice')
})

test('sendText mentions the original sender by contact id after room membership check', async () => {
  const alice = { id: 'wxid_alice', name: () => 'Alice' }
  const room = {
    id: 'room@@abc',
    hasCalls: [],
    sayCalls: [],
    async has(contact) {
      this.hasCalls.push(contact)
      return contact.id === alice.id
    },
    async say(...args) {
      this.sayCalls.push(args)
    },
  }
  const emitted = []

  await sendText(
    { room_id: room.id, text: 'hello', mention_ids: [alice.id] },
    {
      emit: (type, payload) => emitted.push({ type, payload }),
      findRoom: async roomId => roomId === room.id ? room : undefined,
      findContact: async contactId => contactId === alice.id ? alice : undefined,
    },
  )

  assert.deepEqual(room.hasCalls, [alice])
  assert.deepEqual(room.sayCalls, [['hello', alice]])
  assert.deepEqual(emitted, [{
    type: 'send_result',
    payload: { ok: true, command: 'send_text', room_id: room.id },
  }])
})

test('sendText resolves mention target from current room members when contact lookup misses', async () => {
  const alice = { id: 'wxid_alice', name: () => 'Alice' }
  const room = {
    id: 'room@@abc',
    memberAllCalls: 0,
    sayCalls: [],
    async memberAll() {
      this.memberAllCalls += 1
      return [alice]
    },
    async has() {
      throw new Error('room.has should not be needed for memberAll matches')
    },
    async alias(contact) {
      return contact.id === alice.id ? 'Alice Alias' : ''
    },
    async say(...args) {
      this.sayCalls.push(args)
    },
  }

  await sendText(
    { room_id: room.id, text: 'hello', mention_ids: [alice.id] },
    {
      emit: () => {},
      findRoom: async roomId => roomId === room.id ? room : undefined,
      findContact: async () => undefined,
    },
  )

  assert.equal(room.memberAllCalls, 1)
  assert.deepEqual(room.sayCalls, [['hello', alice]])
})

test('sendText treats configured wechat4u puppet as visible mention mode even without runtime internals', async () => {
  const alice = { id: 'wxid_alice', name: () => 'Alice Contact' }
  const room = {
    id: 'room@@abc',
    sayCalls: [],
    async memberAll() {
      return [alice]
    },
    async alias(contact) {
      return contact.id === alice.id ? 'Alice Alias' : ''
    },
    async say(...args) {
      this.sayCalls.push(args)
    },
  }

  await sendText(
    { room_id: room.id, text: 'hello', mention_ids: [alice.id] },
    {
      emit: () => {},
      findRoom: async roomId => roomId === room.id ? room : undefined,
      findContact: async () => undefined,
      getWechat4u: () => null,
      isWechat4u: () => true,
    },
  )

  assert.deepEqual(room.sayCalls, [['@Alice Alias\u2005hello']])
})

test('sendText uses visible room alias mention text for wechat4u', async () => {
  const alice = { id: 'wxid_alice', name: () => 'Alice Contact' }
  const room = {
    id: 'room@@abc',
    sayCalls: [],
    async memberAll() {
      return [alice]
    },
    async has(contact) {
      return contact.id === alice.id
    },
    async alias(contact) {
      return contact.id === alice.id ? 'Alice Alias' : ''
    },
    async say(...args) {
      this.sayCalls.push(args)
    },
  }

  await sendText(
    { room_id: room.id, text: '@Wrong hello', mention_ids: [alice.id] },
    {
      emit: () => {},
      findRoom: async roomId => roomId === room.id ? room : undefined,
      findContact: async () => alice,
      getWechat4u: () => ({}),
    },
  )

  assert.deepEqual(room.sayCalls, [['@Alice Alias\u2005hello']])
})

test('sendText uses wechat4u MsgSource atuserlist for real group mention when runtime internals are available', async () => {
  const alice = { id: '@alice', name: () => 'Alice Contact' }
  const room = {
    id: '@@room',
    sayCalls: [],
    async memberAll() {
      return [alice]
    },
    async alias(contact) {
      return contact.id === alice.id ? 'Alice Alias' : ''
    },
    async say(...args) {
      this.sayCalls.push(args)
    },
  }
  const requests = []
  const wechat4u = {
    CONF: {
      API_webwxsendmsg: 'https://wx.example/cgi-bin/mmwebwx-bin/webwxsendmsg',
      MSGTYPE_TEXT: 1,
    },
    PROP: { passTicket: 'ticket-1' },
    user: { UserName: '@bot' },
    getBaseRequest: () => ({ Uin: '1', Sid: 'sid', Skey: 'skey', DeviceID: 'device' }),
    request: async payload => {
      requests.push(payload)
      return { data: { BaseResponse: { Ret: 0 }, MsgID: 'msg-1' } }
    },
  }

  await sendText(
    { room_id: room.id, text: 'hello', mention_ids: [alice.id] },
    {
      emit: () => {},
      findRoom: async roomId => roomId === room.id ? room : undefined,
      findContact: async () => undefined,
      getWechat4u: () => wechat4u,
    },
  )

  assert.deepEqual(room.sayCalls, [])
  assert.equal(requests.length, 1)
  assert.equal(requests[0].data.Msg.Content, '@Alice Alias\u2005hello')
  assert.equal(requests[0].data.Msg.MsgSource, '<msgsource><atuserlist>@alice</atuserlist></msgsource>')
})

test('sendText falls back to visible mention text when native contact mention fails', async () => {
  const alice = { id: 'wxid_alice', name: () => 'Alice Contact' }
  const room = {
    id: 'room@@abc',
    sayCalls: [],
    async has(contact) {
      return contact.id === alice.id
    },
    async alias(contact) {
      return contact.id === alice.id ? 'Alice Alias' : ''
    },
    async say(...args) {
      this.sayCalls.push(args)
      if (args.length > 1) throw new Error('native mention failed')
    },
  }

  await sendText(
    { room_id: room.id, text: 'hello', mention_ids: [alice.id] },
    {
      emit: () => {},
      findRoom: async roomId => roomId === room.id ? room : undefined,
      findContact: async contactId => contactId === alice.id ? alice : undefined,
    },
  )

  assert.deepEqual(room.sayCalls, [
    ['hello', alice],
    ['@Alice Alias\u2005hello'],
  ])
})

test('sendWechat4uRawTextWithMsgSource sends atuserlist metadata for real group mention', async () => {
  const requests = []
  const wechat4u = {
    CONF: {
      API_webwxsendmsg: 'https://wx.example/cgi-bin/mmwebwx-bin/webwxsendmsg',
      MSGTYPE_TEXT: 1,
    },
    PROP: { passTicket: 'ticket-1' },
    user: { UserName: '@bot' },
    getBaseRequest: () => ({ Uin: '1', Sid: 'sid', Skey: 'skey', DeviceID: 'device' }),
    request: async payload => {
      requests.push(payload)
      return { data: { BaseResponse: { Ret: 0 }, MsgID: 'msg-1', LocalID: 'local-1' } }
    },
  }

  const result = await sendWechat4uRawTextWithMsgSource(
    wechat4u,
    { id: '@@room' },
    'hello',
    [{ id: '@alice', name: 'Alice' }],
  )

  assert.equal(result.ok, true)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].url, wechat4u.CONF.API_webwxsendmsg)
  assert.equal(requests[0].data.Msg.ToUserName, '@@room')
  assert.equal(requests[0].data.Msg.Content, '@Alice\u2005hello')
  assert.equal(requests[0].data.Msg.MsgSource, '<msgsource><atuserlist>@alice</atuserlist></msgsource>')
  assert.deepEqual(requests[0].data.BaseRequest, wechat4u.getBaseRequest())
})

test('sendWechat4uRawTextWithMsgSource accepts wxid member ids for real group mention', async () => {
  const requests = []
  const wechat4u = {
    CONF: {
      API_webwxsendmsg: 'https://wx.example/cgi-bin/mmwebwx-bin/webwxsendmsg',
      MSGTYPE_TEXT: 1,
    },
    PROP: { passTicket: 'ticket-1' },
    user: { UserName: '@bot' },
    getBaseRequest: () => ({ Uin: '1', Sid: 'sid', Skey: 'skey', DeviceID: 'device' }),
    request: async payload => {
      requests.push(payload)
      return { data: { BaseResponse: { Ret: 0 }, MsgID: 'msg-1', LocalID: 'local-1' } }
    },
  }

  await sendWechat4uRawTextWithMsgSource(
    wechat4u,
    { id: '@@room' },
    'hello',
    [{ id: 'wxid_alice', name: 'Alice' }],
  )

  assert.equal(requests.length, 1)
  assert.equal(requests[0].data.Msg.MsgSource, '<msgsource><atuserlist>wxid_alice</atuserlist></msgsource>')
})
