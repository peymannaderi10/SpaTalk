import { COMPANY_NAME, PRIVACY_CONTACT_EMAIL } from "../shared/common";

interface Subprocessor {
  provider: string;
  role: string;
  noTraining: string;
  region: string;
}

/**
 * Public privacy policy. Meta's platform review requires a reachable URL, and
 * the clinics we sell to are health information custodians, so the retention
 * and subprocessor facts are stated on the page rather than linked away.
 */
const subprocessors: Subprocessor[] = [
  {
    provider: "OVHcloud",
    role: "Compute and database backups",
    noTraining: "Infrastructure only",
    region: "Beauharnois, Quebec",
  },
  {
    provider: "Cloudflare",
    role: "DNS, proxy, object storage, edge workers",
    noTraining: "Infrastructure only",
    region: "Edge; storage restricted to a Canadian jurisdiction",
  },
  {
    provider: "Telnyx",
    role: "Telephony and SMS",
    noTraining: "Governed by a data processing agreement",
    region: "Toronto and Montreal anchors",
  },
  {
    provider: "Soniox",
    role: "Speech to text",
    noTraining: "Never used to improve models; real-time audio not stored",
    region: "United States",
  },
  {
    provider: "Inworld",
    role: "Text to speech",
    noTraining: "Never used for training; zero-retention workspace",
    region: "United States",
  },
  {
    provider: "Google (Gemini API, paid tier)",
    role: "Language model",
    noTraining: "Paid tier prompts are not used to improve products",
    region: "United States and other Google regions",
  },
  {
    provider: "Amazon SES",
    role: "Email delivery to clinic staff",
    noTraining: "Infrastructure only",
    region: "ca-central-1",
  },
  {
    provider: "Slack",
    role: "Request delivery, when the clinic opts in",
    noTraining: "The clinic's own workspace",
    region: "The clinic's choice",
  },
  {
    provider: "Stripe",
    role: "Subscription billing for clinics",
    noTraining: "Infrastructure only",
    region: "United States and Canada",
  },
];

export function PrivacyPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-foreground text-3xl font-semibold">Privacy policy</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        How {COMPANY_NAME} handles the information that passes through the
        assistant it runs for a clinic.
      </p>

      <section className="mt-10">
        <h2 className="text-foreground text-xl font-semibold">Our role</h2>
        <p className="text-muted-foreground mt-3 text-sm leading-6">
          {COMPANY_NAME} operates an AI assistant on behalf of a clinic. The
          clinic decides what the assistant is for and is the controller of the
          information it collects. {COMPANY_NAME} is the processor: it handles
          that information only to run the service, and only on the clinic&rsquo;s
          instructions.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-xl font-semibold">
          What we collect
        </h2>
        <ul className="text-muted-foreground mt-3 list-disc space-y-2 pl-5 text-sm leading-6">
          <li>
            Your name, and the phone number or email address you give us so the
            clinic can reach you back.
          </li>
          <li>
            The service or treatment you asked about, and the day or part of the
            day you said you preferred.
          </li>
          <li>
            The transcript of the conversation, whether it happened by phone,
            text message, web chat or a social media message.
          </li>
          <li>
            The phone number that called or texted, and technical delivery
            records such as message identifiers and timestamps.
          </li>
        </ul>
        <p className="text-muted-foreground mt-3 text-sm leading-6">
          Calls are not recorded. Audio is turned into text as the call happens,
          and the audio itself is not kept.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-xl font-semibold">
          Health information
        </h2>
        <p className="text-muted-foreground mt-3 text-sm leading-6">
          The assistant never asks about your health. If you volunteer something
          about a condition or a medication, the conversation is flagged so that
          a person handles it, and the detail stays in the transcript. It is
          never copied into a summary field, a subject line or a notification.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-xl font-semibold">
          How long we keep it
        </h2>
        <ul className="text-muted-foreground mt-3 list-disc space-y-2 pl-5 text-sm leading-6">
          <li>
            Transcripts: 30 days by default, then deleted. A clinic may choose a
            shorter or a longer period.
          </li>
          <li>
            Requests passed to clinic staff, and the usage records used for
            invoicing: 400 days.
          </li>
          <li>
            Records of who read a transcript: 2 years, so that the clinic can
            audit access.
          </li>
        </ul>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-xl font-semibold">
          Where it is processed
        </h2>
        <p className="text-muted-foreground mt-3 text-sm leading-6">
          Our servers and database are in Beauharnois, Quebec. Speech
          recognition, speech synthesis and the language model run with the
          providers below, under terms that forbid training on your
          conversations. Adding a provider to this list is a change to this
          page, not a configuration change.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-foreground border-border border-b">
              <tr>
                <th className="py-2 pr-4 font-semibold">Provider</th>
                <th className="py-2 pr-4 font-semibold">Role</th>
                <th className="py-2 pr-4 font-semibold">
                  Training on your data
                </th>
                <th className="py-2 font-semibold">Region</th>
              </tr>
            </thead>
            <tbody className="text-muted-foreground">
              {subprocessors.map((sub) => (
                <tr key={sub.provider} className="border-border border-b">
                  <td className="py-2 pr-4">{sub.provider}</td>
                  <td className="py-2 pr-4">{sub.role}</td>
                  <td className="py-2 pr-4">{sub.noTraining}</td>
                  <td className="py-2">{sub.region}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-xl font-semibold">Your choices</h2>
        <p className="text-muted-foreground mt-3 text-sm leading-6">
          Reply STOP to any text message to stop receiving them, and START to
          begin again. To ask what we hold about you, or to have it deleted
          before the retention period ends, write to{" "}
          <a
            className="text-foreground underline"
            href={`mailto:${PRIVACY_CONTACT_EMAIL}`}
          >
            {PRIVACY_CONTACT_EMAIL}
          </a>
          . We pass the request to the clinic, who decides, and we act on their
          answer.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-foreground text-xl font-semibold">Contact</h2>
        <p className="text-muted-foreground mt-3 text-sm leading-6">
          {COMPANY_NAME},{" "}
          <a
            className="text-foreground underline"
            href={`mailto:${PRIVACY_CONTACT_EMAIL}`}
          >
            {PRIVACY_CONTACT_EMAIL}
          </a>
          .
        </p>
      </section>
    </main>
  );
}
