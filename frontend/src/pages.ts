// Static text pages. Everything marked DRAFT or PLACEHOLDER is for Akhil to review or write.

export interface StaticPage { title: string; description: string; html: string }

const draft = (what: string) =>
  `<p class="placeholder"><strong>Draft for Akhil:</strong> ${what}</p>`;

export const STATIC_PAGES: Record<string, StaticPage> = {
  "/about": {
    title: "About",
    description: "What Six Star Playbook is and who runs it.",
    html: `
      ${draft("placeholder text. Replace with your own words about who runs the site and why.")}
      <p>Six Star Playbook answers GTA 6 questions fast. Ask one, get a short answer written from our A to Z guide, with a link to the section it came from.</p>
      <p>It's a free fan project. No account, no paywall.</p>
      <h2>How it works</h2>
      <ul>
        <li>We keep one guide, checked against public sources.</li>
        <li>An AI model reads only that guide and writes your answer.</li>
        <li>Every claim gets a tag: Confirmed, Rumor or Not confirmed.</li>
      </ul>
      <p>More on that on the <a href="/about/accuracy">Accuracy</a> page.</p>`,
  },
  "/about/accuracy": {
    title: "Accuracy",
    description: "How Six Star Playbook labels answers as Confirmed, Rumor or Not confirmed, and how to report a mistake.",
    html: `
      ${draft("review this text and adjust it to match how you actually check the guide.")}
      <p>Answers are written by AI from our guide, and only from our guide. They can still be wrong, so every answer links to the guide section it used.</p>
      <h2>What the tags mean</h2>
      <ul class="tag-legend">
        <li><span class="tag tag-confirmed">Confirmed</span> The guide cites an official or well-sourced statement for it.</li>
        <li><span class="tag tag-rumor">Rumor</span> Reported or leaked, not confirmed. Treat it as a maybe.</li>
        <li><span class="tag tag-not_confirmed">Not confirmed</span> The guide doesn't back it up, or nobody has said yet.</li>
      </ul>
      <h2>When we don't know</h2>
      <p>If the guide doesn't cover your question, the answer says "That isn't confirmed yet" instead of guessing.</p>
      <h2>Spotted a mistake?</h2>
      <p>Use the Report button under any answer. Reports go straight to the person who maintains the guide.</p>`,
  },
  "/privacy": {
    title: "Privacy",
    description: "What Six Star Playbook stores when you ask a question.",
    html: `
      ${draft("this describes what the software does today. It is not legal advice; have it checked and add your contact details before launch.")}
      <h2>What we store</h2>
      <ul>
        <li><strong>Your questions.</strong> We log the question text to see what players ask and to improve the guide. Don't put personal details in a question.</li>
        <li><strong>A random browser id.</strong> Kept in your browser's local storage and sent with each question so we can apply fair-use limits. It isn't tied to your name or an account.</li>
        <li><strong>Your IP address, for limits.</strong> Used to count requests. In the question log it is stored only as a salted hash, never in plain form.</li>
        <li><strong>Feedback and reports.</strong> Helpful or Not helpful votes, and any note you send with a report.</li>
      </ul>
      <h2>What we don't do</h2>
      <ul>
        <li>No accounts, no ads profile, no selling of data.</li>
      </ul>
      <h2>Who else sees a question</h2>
      <p>Questions are sent to Anthropic's Claude API to write the answer. Fonts load from Google Fonts.</p>
      <p class="placeholder"><strong>Placeholder:</strong> data retention period, hosting providers and a contact for privacy requests.</p>`,
  },
  "/terms": {
    title: "Terms",
    description: "Terms of use for Six Star Playbook.",
    html: `
      ${draft("placeholder terms. Replace with your own before launch.")}
      <ul>
        <li>Six Star Playbook is a free, unofficial fan site, provided as is.</li>
        <li>Answers are written by AI and can be wrong. Check the linked source before relying on one.</li>
        <li>Don't abuse the service: no scraping, flooding or attempts to get around the question limits.</li>
        <li>We may change or stop the service at any time.</li>
      </ul>`,
  },
  "/contact": {
    title: "Contact",
    description: "How to reach Six Star Playbook.",
    html: `
      <p class="placeholder"><strong>Placeholder for Akhil:</strong> add a contact email or form link here.</p>
      <p>Found a wrong answer? The fastest route is the Report button under that answer.</p>`,
  },
};
