export interface ConnectorApp {
  name: string;
  color: string;
}

export const connectorApps: ConnectorApp[] = [
  { name: "Slack", color: "#611f69" },
  { name: "Drive", color: "#1fa463" },
  { name: "Jira", color: "#2684ff" },
  { name: "Notion", color: "#111111" },
  { name: "Gmail", color: "#ea4335" },
  { name: "Salesforce", color: "#00a1e0" },
  { name: "Confluence", color: "#172b4d" },
  { name: "Zendesk", color: "#03363d" },
  { name: "GitHub", color: "#24292e" },
  { name: "Asana", color: "#f06a6a" },
  { name: "HubSpot", color: "#ff7a59" },
  { name: "Teams", color: "#4b53bc" },
  { name: "Box", color: "#0061d5" },
  { name: "ServiceNow", color: "#62d84e" },
  { name: "Zoom", color: "#2d8cff" },
  { name: "Airtable", color: "#fcb400" },
];

export interface HeroRotationItem {
  q: string;
  s: string;
  a: string;
  tags: string[];
}

export const heroRotationItems: HeroRotationItem[] = [

  {
    q:"What's our refund policy for annual plans?",
    s:"across Policy docs · Help center · Slack",
    a:"Annual plans get a <b>full refund within 30 days</b> of purchase; after that, refunds are pro-rated to the unused months — from the billing policy updated in January.",
    tags:["Billing policy","Help center","Slack thread"]
  },
  {
    q:"Has any customer reported this login issue before?",
    s:"across Support tickets · Product logs",
    a:"Yes — <b>3 similar tickets</b> in the last month, all resolved by resetting the session token. The past fix and the steps are attached.",
    tags:["Support tickets","Past resolution","Product logs"]
  },
  {
    q:"How many leave days do new employees get?",
    s:"across HR policy · Employee handbook",
    a:"New employees get <b>18 paid leave days</b> per year plus public holidays, starting from day one — from the HR policy, effective January 2026.",
    tags:["HR policy","Employee handbook"]
  }
];

export interface MockRow {
  color: string;
  text: string;
}

export interface CapabilityTab {
  key: string;
  label: string;
  heading: string;
  body: string;
  mockRows: MockRow[];
}

export const capabilityTabs: CapabilityTab[] = [
  {
    key: "answers",
    label: "Get answers",
    heading: "Make better decisions with confident answers",
    body: "Gsearch turns your docs, chats, and meeting notes into direct answers — so your team spends less time searching and more time acting. Every answer cites its source.",
    mockRows: [
      { color: "var(--teal)", text: "Is this repair covered under warranty?" },
      { color: "var(--gold)", text: "<b>Answer:</b> Yes — covered until Mar 2027" },
      { color: "var(--violet)", text: "Source: Service contract · cited" },
    ],
  },
  {
    key: "resources",
    label: "Find resources",
    heading: "Find exactly what you need, the moment you need it",
    body: "Stop digging through ten apps. Gsearch surfaces the right document, person, or thread from across your whole stack in one search.",
    mockRows: [
      { color: "var(--teal)", text: "Latest pricing deck — <b>found in Drive</b>" },
      { color: "var(--violet)", text: "Owner: Marketing team · updated 2 days ago" },
      { color: "var(--gold)", text: "Related discussion found in chat" },
    ],
  },
  {
    key: "create",
    label: "Create content",
    heading: "Create anything, without starting from scratch",
    body: "Generate reports, summaries, replies, and docs using your existing knowledge — so your team spends less time building and more time shipping.",
    mockRows: [
      { color: "var(--gold)", text: "Draft: customer follow-up email" },
      { color: "var(--teal)", text: "Pulled from: last 3 tickets + contract" },
      { color: "var(--violet)", text: "Ready to send ✓" },
    ],
  },
  {
    key: "analyze",
    label: "Analyze data",
    heading: "Turn scattered data into clear insight",
    body: "Ask a question that spans systems and Gsearch connects the data to answer it — surfacing the pattern no single dashboard could show.",
    mockRows: [
      { color: "var(--teal)", text: "Why are customers cancelling?" },
      { color: "var(--gold)", text: "Pattern found: setup issues in week 1" },
      { color: "var(--violet)", text: "Connected across 3 sources" },
    ],
  },
  {
    key: "automate",
    label: "Automate tasks",
    heading: "Automate the tasks your team does every day",
    body: "Connect your apps and build multi-step workflows with no code. Handle routine work automatically or chain actions across tools.",
    mockRows: [
      { color: "var(--teal)", text: "Trigger: new support ticket" },
      { color: "var(--gold)", text: "Find related cases + draft reply" },
      { color: "var(--violet)", text: "Route to the right owner ✓" },
    ],
  },
];

export interface TeamTab {
  key: string;
  label: string;
  heading: string;
  body: string;
  ctaLabel: string;
  pills: string[];
  example: string;
}

export const teamTabs: TeamTab[] = [
  {
    key: "support",
    label: "Support",
    heading: "Resolve tickets before they escalate",
    body: "Connect a customer issue to past resolutions, product logs, and the right expert — in one answer your reps can trust.",
    ctaLabel: "Gsearch for Support →",
    pills: ["help desk", "knowledge base", "product logs"],
    example: '"Has this customer hit this issue before?" → answered in seconds, with the past fix attached.',
  },
  {
    key: "sales",
    label: "Sales",
    heading: "Walk into every call prepared",
    body: "Connect a contact to their threads, contracts, and open issues across CRM, email, and docs — without the pre-call scramble.",
    ctaLabel: "Gsearch for Sales →",
    pills: ["CRM", "email", "contracts", "tickets"],
    example: "The full relationship in one view — not just the last note.",
  },
  {
    key: "ops",
    label: "Operations",
    heading: "Find the record, not the haystack",
    body: "Surface the service record, manual, and approval chain for any asset — connected across every system instead of searched ten times.",
    ctaLabel: "Gsearch for Operations →",
    pills: ["service records", "manuals", "approvals"],
    example: "One asset, one connected view across every tool.",
  },
  {
    key: "eng",
    label: "Engineering",
    heading: "Resolve blockers with less disruption",
    body: "Connect code, runbooks, and past incidents to get the decision and the reasoning behind it — without digging through wikis.",
    ctaLabel: "Gsearch for Engineering →",
    pills: ["codebase", "runbooks", "incidents", "PRs"],
    example: '"Why did checkout fail last release?" → answered across services and past incidents.',
  },
  {
    key: "hr",
    label: "HR",
    heading: "Answer policy questions in your voice",
    body: "Connect employees to policies, benefits, and people resources instantly — with the source and effective date attached.",
    ctaLabel: "Gsearch for HR →",
    pills: ["policies", "benefits", "people data"],
    example: "Fewer repeat questions; answers that cite the real document.",
  },
];

export interface FaqItem {
  question: string;
  answer: string;
}

export const faqItems: FaqItem[] = [
  {
    question: "Why do you call Gsearch a \"second brain\"?",
    answer:
      "Because it works like one. Gsearch doesn't just store your company's knowledge — it connects it, remembers how things relate, and recalls the right answer the moment anyone asks. Unlike personal note-taking apps, this is a second brain for your whole company, built on the tools you already use.",
  },
  {
    question: "Do we have to move our data into Gsearch?",
    answer:
      "No. Gsearch connects to the tools you already use and reads answers from the source. With federated connectors, sensitive data never leaves its original system — nothing is copied or migrated.",
  },
  {
    question: "How long does setup take?",
    answer:
      "Most teams are getting useful answers within days. Connect your sources, your existing permissions carry over automatically, and there's no new infrastructure to stand up.",
  },
  {
    question: "Will people see things they shouldn't?",
    answer:
      "No. Gsearch is permission-aware by design. Every answer respects the access rules already set in your tools, so each person only ever sees what they're authorized to see.",
  },
  {
    question: "How is this different from regular search or a chatbot?",
    answer:
      "Most tools return the document closest to your words. Gsearch connects the facts across your tools to answer questions no single document holds — and cites every source so you can trust the answer.",
  },
  {
    question: "Is our data used to train AI models?",
    answer:
      "No. Your queries and data are never stored for training. You can also bring your own cloud and model keys to keep everything inside your own environment.",
  },
  {
    question: "Which tools does Gsearch connect to?",
    answer:
      "100+ of the apps your team already uses — from Slack, Drive, and Jira to Salesforce, Confluence, and Zendesk — plus custom connectors for anything specific to your stack.",
  },
];
