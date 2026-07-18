const WORDS = [
  'ALPINE', 'BIRCH', 'CEDAR', 'DENALI', 'EVEREST', 'FJORD',
  'GLACIER', 'HARBOR', 'IRIS', 'JUNIPER', 'KAURI', 'LINDEN',
  'MAPLE', 'NORWOOD', 'OAKLEY', 'PINE', 'QUARTZ', 'RIDGE',
  'SEQUOIA', 'TUNDRA', 'UMBER', 'VALLEY', 'WILLOW', 'ZENITH',
]

export function generateToken(): string {
  const word = WORDS[Math.floor(Math.random() * WORDS.length)]
  const num = Math.floor(1000 + Math.random() * 9000)
  return `${word}-${num}`
}
