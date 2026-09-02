"""
Cost model for the AI front desk. All provider rates in USD unless noted.
Rates are loaded from rates.json (filled from research notes). Exits non-zero
if any recommended stack breaches a hard ceiling from brief section 8.
"""
import json, sys, itertools

R = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "rates.json"))
FX = R["usd_to_cad"]

# ---- Call-shape assumptions (stated in the design doc) -------------------
A = R["assumptions"]
AVG_CALL_MIN      = A["avg_call_minutes"]        # typical front-desk call
AGENT_SPEAK_FRAC  = A["agent_speaking_fraction"] # share of wall-clock the agent is talking
CHARS_PER_MIN     = A["chars_per_spoken_minute"] # ~150 wpm * ~5.5 chars/word incl. spaces
TURNS_PER_MIN     = A["turns_per_minute"]        # LLM calls per call-minute
IN_TOK_UNCACHED   = A["input_tokens_uncached_per_turn"]  # dynamic part: history + transcript
IN_TOK_CACHED     = A["input_tokens_cached_per_turn"]    # static part: system prompt + KB + tools
OUT_TOK           = A["output_tokens_per_turn"]

def llm_cost_per_turn(llm):
    return (IN_TOK_UNCACHED * llm["in"] + IN_TOK_CACHED * llm["cached_in"] + OUT_TOK * llm["out"]) / 1e6

def voice_per_minute(tel, stt, tts, llm):
    c_tel = tel["inbound_per_min"] + tel.get("stream_per_min", 0) + tel.get("record_per_min", 0)
    c_stt = stt["per_min"]
    c_tts = AGENT_SPEAK_FRAC * CHARS_PER_MIN * tts["per_1m_chars"] / 1e6
    c_llm = TURNS_PER_MIN * llm_cost_per_turn(llm)
    total = c_tel + c_stt + c_tts + c_llm
    return dict(tel=c_tel, stt=c_stt, tts=c_tts, llm=c_llm, total_usd=total, total_cad=total * FX)

T = R["assumptions_text"]
def text_conversation(sms, llm, channel="sms"):
    turns = T["turns_per_conversation"]
    c_llm = turns * llm_cost_per_turn(llm)
    if channel == "sms":
        c_msg = T["outbound_msgs"] * (sms["out_per_msg"] + sms["carrier_out_per_msg"]) + T["inbound_msgs"] * (sms["in_per_msg"] + sms["carrier_in_per_msg"])
    else:
        c_msg = 0.0
    total = c_llm + c_msg
    return dict(llm=c_llm, msgs=c_msg, total_usd=total, total_cad=total * FX)

def outbound_message(sms):
    c = sms["out_per_msg"] + sms["carrier_out_per_msg"]
    return dict(total_usd=c, total_cad=c * FX)

CEIL = R["ceilings_cad"]
fail = False

def check(label, cad, target, ceiling, counts=True):
    global fail
    flag = "OK" if cad <= target else ("OVER TARGET" if cad <= ceiling else "BREACH")
    if flag == "BREACH" and counts: fail = True
    print(f"  {label:<48} {cad:8.4f} CAD  target {target:.3f}  ceiling {ceiling:.3f}  {flag}")

print("=== VOICE, per call-minute (all-in) ===")
for name, stack in R["voice_stacks"].items():
    v = voice_per_minute(R["telephony"][stack["tel"]], R["stt"][stack["stt"]], R["tts"][stack["tts"]], R["llm"][stack["llm"]])
    print(f"\n{name}: tel={stack['tel']} stt={stack['stt']} tts={stack['tts']} llm={stack['llm']}")
    print(f"  breakdown USD/min: tel {v['tel']:.4f}  stt {v['stt']:.4f}  tts {v['tts']:.4f}  llm {v['llm']:.4f}")
    check("per call-minute", v["total_cad"], CEIL["voice_min_target"], CEIL["voice_min_ceiling"], counts=bool(stack.get("recommended")))
    if stack.get("recommended"):
        print(f"  -> avg call of {AVG_CALL_MIN} min costs {v['total_cad']*AVG_CALL_MIN:.3f} CAD")

print("\n=== TEXT conversation (SMS incl. carrier fees; chat has no msg cost) ===")
for name, stack in R["text_stacks"].items():
    t = text_conversation(R["sms"][stack["sms"]], R["llm"][stack["llm"]], "sms")
    c = text_conversation(R["sms"][stack["sms"]], R["llm"][stack["llm"]], "chat")
    print(f"\n{name}: sms={stack['sms']} llm={stack['llm']}")
    rec = bool(stack.get("recommended"))
    check("SMS conversation", t["total_cad"], CEIL["text_conv_target"], CEIL["text_conv_ceiling"], counts=rec)
    check("web-chat conversation", c["total_cad"], CEIL["text_conv_target"], CEIL["text_conv_ceiling"], counts=rec)
    o = outbound_message(R["sms"][stack["sms"]])
    check("single outbound SMS", o["total_cad"], CEIL["outbound_msg_target"], CEIL["outbound_msg_ceiling"], counts=rec)

print("\n=== FIXED platform cost, CAD/month ===")
for n_tenants, bom in R["fixed_cad"].items():
    total = sum(bom.values())
    tgt = CEIL["fixed"][n_tenants]
    flag = "OK" if total < tgt else "BREACH"
    if flag == "BREACH": fail = True
    print(f"  {n_tenants:>2} tenants: {total:7.2f} CAD  (ceiling {tgt})  {flag}   " + ", ".join(f"{k} {v}" for k, v in bom.items()))

print("\n=== MARGIN at 999 CAD/tenant/month (recommended stack, brief 8.4) ===")
rec_v = next(s for s in R["voice_stacks"].values() if s.get("recommended"))
rec_t = next(s for s in R["text_stacks"].values() if s.get("recommended"))
v = voice_per_minute(R["telephony"][rec_v["tel"]], R["stt"][rec_v["stt"]], R["tts"][rec_v["tts"]], R["llm"][rec_v["llm"]])
t = text_conversation(R["sms"][rec_t["sms"]], R["llm"][rec_t["llm"]], "sms")
M = R["assumptions_volume"]
per_tenant_variable = (M["calls_per_month"] * AVG_CALL_MIN * v["total_cad"]
                       + M["sms_convs_per_month"] * t["total_cad"]
                       + M["chat_convs_per_month"] * text_conversation(R["sms"][rec_t["sms"]], R["llm"][rec_t["llm"]], "chat")["total_cad"]
                       + M["outbound_msgs_per_month"] * outbound_message(R["sms"][rec_t["sms"]])["total_cad"]
                       + R["per_tenant_fixed_cad"])
print(f"  variable+per-tenant cost per tenant: {per_tenant_variable:.2f} CAD/month  (calls {M['calls_per_month']}, sms convs {M['sms_convs_per_month']}, chat convs {M['chat_convs_per_month']}, outbound {M['outbound_msgs_per_month']})")
for n in (1, 3, 10, 25):
    key = str(n) if str(n) in R["fixed_cad"] else max(k for k in R["fixed_cad"] if int(k) <= n)
    fixed = sum(R["fixed_cad"][key].values())
    cost = per_tenant_variable * n + fixed
    rev = 999 * n
    gm = (rev - cost) / rev
    need = {1: 0.65, 3: 0.80}.get(n)
    flag = "" if need is None else ("OK" if gm >= need else "BREACH")
    if flag == "BREACH": fail = True
    print(f"  {n:>2} tenants: cost {cost:8.2f}  revenue {rev:6d}  gross margin {gm*100:5.1f}%  {('need ' + str(int(need*100)) + '% ' + flag) if need else ''}")

# sensitivity: what if calls are twice as long / twice as many
print("\n=== SENSITIVITY (recommended voice stack) ===")
for mult in (1.0, 1.5, 2.0):
    print(f"  calls x{mult}: per-tenant variable {(per_tenant_variable - R['per_tenant_fixed_cad']) * mult + R['per_tenant_fixed_cad']:.2f} CAD/month")

sys.exit(1 if fail else 0)
