// Debug script to simulate stage response data flow
console.log('=== STAGE RESPONSE DEBUG ===');

// Simulate the data that would come from WebSocket
const simulatedWebSocketData = {
  "type": "stage_response",
  "stageId": "ask_security_medium", 
  "responseType": "bullet",
  "prompt": "쏠 어플에서도 지금 만든 계좌를 사용하실 수 있도록 도와드릴게요. 보유하신 보안매체 등록해드릴까요?",
  "choices": [
    {"value": "보유한 보안매체 1 (당행)", "label": "🔐 보유한 보안매체 1 (당행)"},
    {"value": "보유한 보안매체 2 (타행)", "label": "🏦 보유한 보안매체 2 (타행)"},
    {"value": "보안카드", "label": "💳 보안카드 (신규 발급)"},
    {"value": "신한OTP (10,000원)", "label": "📱 신한OTP (10,000원)"}
  ],
  "skippable": false,
  "modifiableFields": null
};

console.log('WebSocket data:', simulatedWebSocketData);

// Simulate what chatStore would create for currentStageResponse
const currentStageResponse = {
  type: 'stage_response',
  stageId: simulatedWebSocketData.stageId,
  responseType: simulatedWebSocketData.responseType,
  prompt: simulatedWebSocketData.prompt,
  choices: simulatedWebSocketData.choices,
  skippable: simulatedWebSocketData.skippable || false,
  modifiableFields: simulatedWebSocketData.modifiableFields
};

console.log('Stage response object:', currentStageResponse);

// Simulate message object that would be added to messages array
const messageObject = {
  id: 'test-id',
  sender: 'ai',
  text: '', // Empty for stage response
  timestamp: new Date(),
  isStreaming: false,
  stageResponse: currentStageResponse
};

console.log('Message object:', messageObject);

// Test the condition that would trigger StageResponse component
console.log('=== COMPONENT RENDERING CHECKS ===');
console.log('message.stageResponse exists?', !!messageObject.stageResponse);
console.log('responseType === "bullet"?', messageObject.stageResponse.responseType === 'bullet');
console.log('choices array exists?', !!messageObject.stageResponse.choices);
console.log('choices array length:', messageObject.stageResponse.choices?.length || 0);
console.log('choices array contents:', messageObject.stageResponse.choices);

// Test individual choice rendering
if (messageObject.stageResponse.choices) {
  console.log('=== CHOICE BUTTON RENDERING ===');
  messageObject.stageResponse.choices.forEach((choice, index) => {
    console.log(`Choice ${index}:`);
    console.log(`  - choice.value: "${choice.value}"`);
    console.log(`  - choice.label: "${choice.label}"`);
    console.log(`  - key for v-for: "${choice.value}"`);
    console.log(`  - aria-label: "선택: ${choice.label}"`);
    console.log(`  - button text: "${choice.label}"`);
  });
}