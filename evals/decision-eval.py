"""Independent artifact scoring for completed quotes, separate from historical replay."""
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path


CRITERIA = ('identity', 'source_fitness', 'manufacturing', 'cost_arithmetic',
            'completeness_terms', 'trace_integrity', 'independent_review', 'human_handoff')


def drawing_asset_reference(value):
    return isinstance(value, str) and ('/' in value or '\\' in value or value.lower().endswith(
        ('.pdf', '.dwg', '.dxf', '.step', '.stp', '.iges', '.igs', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.svg')))


def evaluate(config, h):
    h.shape(config, ('schema_version', 'challenge', 'assessment', 'ledger', 'artifacts', 'out'))
    h.require(config['schema_version'] == 1, 'INVALID_DECISION_CONFIG')
    evidence = h.EvidenceIO()
    challenge = evidence.json(config['challenge'])
    h.shape(challenge, ('schema_version', 'kind', 'frozen_at', 'cohort', 'cases'))
    h.require(challenge['schema_version'] == 1 and challenge['kind'] == 'frozen_full_rfq_challenge' and
              challenge['cohort'] in ('exposed_diagnostic', 'synthetic', 'independent_live'), 'INVALID_CHALLENGE')
    frozen_at = h.timestamp(challenge['frozen_at'])
    frozen = challenge['cases']
    h.require(isinstance(frozen, list) and 0 < len(frozen) <= 10000 and
              len({c['id'] for c in frozen}) == len(frozen), 'FROZEN_CASES_MISSING_OR_DUPLICATE')
    for case in frozen:
        h.shape(case, ('id', 'cohort', 'request', 'requirements', 'assessment_case_id', 'review_assignment', 'allowed_sources', 'blocked_evidence'),
                ('id', 'cohort', 'request', 'requirements', 'assessment_case_id', 'review_assignment', 'allowed_sources'))
        h.text(case['id'])
        h.require(case['cohort'] in ('eligible_quote', 'predeclared_blocked', 'excluded'), 'INVALID_ELIGIBILITY')
        if case['cohort'] == 'predeclared_blocked':
            h.require('blocked_evidence' in case, 'BLOCKED_COHORT_EVIDENCE_REQUIRED')
    cases = {c['id']: c for c in frozen}
    assessment = evidence.json(config['assessment'])
    h.require(assessment.get('schema_version') == 1 and assessment.get('kind') == 'keller-ground-truth-assessment' and
              isinstance(assessment.get('cases'), list) and len({c['id'] for c in assessment['cases']}) == len(assessment['cases']) ==
              assessment['summary']['cases'], 'INVALID_INDEPENDENT_ASSESSMENT')
    for path, sha256 in assessment['inputs'].items():
        evidence.read({'path': path, 'sha256': sha256})
    assessed = {c['id']: c for c in assessment['cases']}
    ledger = evidence.json(config['ledger'])
    h.shape(ledger, ('schema_version', 'kind', 'challenge_sha256', 'sealed_at', 'attempts'))
    h.require(ledger['schema_version'] == 1 and ledger['kind'] == 'sealed_execution_ledger' and
              ledger['challenge_sha256'] == config['challenge']['sha256'] and
              h.timestamp(ledger['sealed_at']) >= frozen_at and isinstance(ledger['attempts'], list) and
              len(ledger['attempts']) <= 10000, 'INVALID_EXECUTION_LEDGER')
    artifacts = evidence.json(config['artifacts'])
    h.shape(artifacts, ('schema_version', 'kind', 'ledger_sha256', 'attempts'))
    h.require(artifacts['schema_version'] == 1 and artifacts['kind'] == 'sealed_quote_artifacts' and
              artifacts['ledger_sha256'] == config['ledger']['sha256'] and isinstance(artifacts['attempts'], list) and
              len(artifacts['attempts']) <= 10000, 'INVALID_ARTIFACT_MANIFEST')
    observed, outputs = defaultdict(list), defaultdict(list)
    for item in ledger['attempts']:
        h.require(isinstance(item, dict) and isinstance(item.get('attempt_id'), str) and isinstance(item.get('case_id'), str), 'UNASSIGNABLE_LEDGER_ATTEMPT')
        observed[item['attempt_id']].append(item)
    for item in artifacts['attempts']:
        h.require(isinstance(item, dict) and isinstance(item.get('attempt_id'), str) and isinstance(item.get('case_id'), str), 'UNASSIGNABLE_ARTIFACT_ATTEMPT')
        outputs[item['attempt_id']].append(item)
    work = list(ledger['attempts'])
    for item in artifacts['attempts']:
        if item['attempt_id'] not in observed:
            work.append({**item, 'status': 'ORPHAN_ARTIFACT_ATTEMPT'})
    attempted_cases = {a['case_id'] for a in work}
    for case in frozen:
        if case['cohort'] != 'excluded' and case['id'] not in attempted_cases:
            work.append({'case_id': case['id'], 'attempt_id': 'MISSING:' + case['id'], 'status': 'MISSING_ATTEMPT'})
    results = []
    for attempt in work:
        case_id, attempt_id = attempt['case_id'], attempt['attempt_id']
        case = cases.get(case_id)
        verdicts = {key: {'pass': False, 'reason': 'NOT_VERIFIED'} for key in CRITERIA}
        errors, numeric = [], []
        status = attempt.get('status', 'INVALID')
        cohort = case['cohort'] if case else 'undeclared'
        result = {'case_id': case_id, 'attempt_id': attempt_id, 'cohort': cohort, 'attempt_status': status,
                  'criteria': verdicts, 'completed_quote_all_pass': False, 'safety_hold_all_pass': False,
                  'errors': errors, 'numeric_proposals': numeric}
        results.append(result)
        def criterion(key, fn):
            try:
                fn()
                verdicts[key] = {'pass': True, 'reason': 'SOURCE_AND_ARTIFACT_CHECK_PASSED'}
                return True
            except (ValueError, OSError, KeyError, TypeError, ArithmeticError, IndexError, AttributeError) as error:
                reason = str(error) if isinstance(error, ValueError) else 'MALFORMED_OR_UNAVAILABLE_EVIDENCE'
                verdicts[key] = {'pass': False, 'reason': reason}
                errors.append(key + ':' + reason)
                return False
        try:
            h.require(case is not None and cohort != 'excluded', 'UNDECLARED_OR_EXCLUDED_ATTEMPT')
            h.require(len(observed[attempt_id]) == 1 and len(outputs[attempt_id]) == 1, 'MISSING_DROPPED_DUPLICATE_OR_ORPHAN_ATTEMPT')
            artifact = outputs[attempt_id][0]
            result['observed_attempt'] = attempt
            result['artifact_references'] = artifact
            h.shape(artifact, ('case_id', 'attempt_id', 'trace', 'draft', 'price_decisions', 'review', 'review_receipt', 'handoff'),
                    ('case_id', 'attempt_id'))
            h.require(artifact['case_id'] == case_id, 'ARTIFACT_CASE_IDENTITY_MISMATCH')
            artifact_integrity = {}
            for key in ('trace', 'draft', 'price_decisions', 'review', 'review_receipt', 'handoff'):
                if key in artifact:
                    try:
                        reference = artifact[key]['source'] if key in ('review_receipt', 'handoff') else artifact[key]
                        evidence.read(reference)
                        artifact_integrity[key] = 'VERIFIED_REFERENCED_BYTES'
                    except (ValueError, OSError, KeyError, TypeError):
                        artifact_integrity[key] = 'UNVERIFIED_REFERENCED_BYTES'
            result['artifact_integrity'] = artifact_integrity
            h.require(all(v == 'VERIFIED_REFERENCED_BYTES' for v in artifact_integrity.values()), 'ARTIFACT_BYTES_UNVERIFIED')
            h.shape(attempt, ('case_id', 'attempt_id', 'producer_id', 'status', 'started_at', 'finished_at', 'receipt'))
            producer = h.text(attempt['producer_id'])
            start, finish = h.timestamp(attempt['started_at']), h.timestamp(attempt['finished_at'])
            h.require(frozen_at < start <= finish <= h.timestamp(ledger['sealed_at']), 'ATTEMPT_NOT_AFTER_FROZEN_CHALLENGE')
            h.require(status in ('COMPLETED', 'HELD', 'ERROR', 'TIMED_OUT', 'INVALID'), 'INVALID_ATTEMPT_STATE')
            request = evidence.json(case['request'])
            requirements = evidence.json(case['requirements'])
            h.require(requirements.get('kind') == 'full_rfq_requirements' and requirements.get('schema_version') == 1 and
                      requirements.get('case_id') == case_id and isinstance(requirements.get('lines'), list) and
                      requirements['lines'] and isinstance(request.get('parts'), list), 'FULL_RFQ_REQUIREMENTS_MISSING')
            target_cases = {line['line_id']: assessed[line.get('assessment_case_id', case['assessment_case_id'])]
                            for line in requirements['lines']}
            receipt = h.bound_record(attempt['receipt'], evidence)
            h.require(receipt.get('kind') == 'workflow_execution_receipt' and receipt.get('attempt_id') == attempt_id and
                      receipt.get('case_id') == case_id and receipt.get('producer_id') == producer and
                      receipt.get('status') == status and receipt.get('request_sha256') == case['request']['sha256'] and
                      receipt.get('started_at') == attempt['started_at'] and receipt.get('finished_at') == attempt['finished_at'], 'EXECUTION_RECEIPT_MISMATCH')
            h.require(status in ('COMPLETED', 'HELD'), 'ATTEMPT_' + status)
            draft = evidence.json(artifact['draft'])
            decisions = evidence.json(artifact['price_decisions'])
            trace = evidence.json(artifact['trace'])
            for key in ('trace', 'draft', 'price_decisions'):
                h.require(receipt.get(key + '_sha256') == artifact[key]['sha256'], 'EXECUTION_ARTIFACT_HASH_MISMATCH')
            assignment = h.bound_record(case['review_assignment'], evidence)
            h.require(assignment.get('kind') == 'independent_review_assignment' and assignment.get('case_id') == case_id and
                      h.timestamp(assignment['assigned_at']) <= frozen_at and
                      h.text(assignment['reviewer_id']).casefold() != producer.casefold() and
                      h.text(assignment['executor_id']).casefold() != producer.casefold() and
                      assignment.get('method') in ('human_source_review', 'separate_blinded_review_job'), 'INDEPENDENT_REVIEW_ASSIGNMENT_INVALID')
            source_records = {}
        except (ValueError, OSError, KeyError, TypeError, ArithmeticError, IndexError, AttributeError) as error:
            reason = str(error) if isinstance(error, ValueError) else 'MALFORMED_OR_UNAVAILABLE_ARTIFACT'
            errors.append(reason)
            for key in verdicts:
                verdicts[key]['reason'] = reason
            continue
        def check_identity():
            h.require(draft.get('schema_version') == 1 and draft.get('request') == request and draft.get('order_id') == request.get('order_id') and
                      draft.get('customer') == request.get('customer') and draft.get('quote_date') == request.get('quote_date') == requirements.get('quote_date') and
                      draft.get('currency') == requirements.get('currency') and request.get('customer_id') == requirements.get('customer_id'), 'REQUEST_DRAFT_IDENTITY_MISMATCH')
            parts, lines = request['parts'], draft['lines']
            wanted = requirements['lines']
            h.require(len(parts) == len(lines) == len(wanted) and len({p['line_id'] for p in parts}) == len(parts) and
                      len({p['line_id'] for p in wanted}) == len(wanted), 'HIDDEN_MISSING_OR_DUPLICATE_LINE')
            for part, line, requirement in zip(parts, lines, wanted):
                h.require(part['line_id'] == line['line_id'] == requirement['line_id'] and
                          line['part'] == {k: v for k, v in part.items() if k not in ('line_id', 'pricing')}, 'ALTERED_OR_REORDERED_LINE')
                identity = requirement['identity']
                h.verify_identity(identity, identity, full=True)
                h.require(part.get('part_no') == identity['part_no'] and h.number(part['quantity'], True, 0) ==
                          h.number(identity['quantity'], True, 0) and identity['customer_id'] == request['customer_id'] and
                          identity['currency'] == requirements['currency'], 'RFQ_SOURCE_IDENTITY_MISMATCH')
                for key in ('revision', 'rev'):
                    if key in part:
                        h.require(h.text(part[key]) == identity['revision'], 'RFQ_REVISION_CONFLICT')
                if 'drawing_no' in part:
                    h.require(h.text(part['drawing_no']) == identity['drawing_no'], 'RFQ_DRAWING_CONFLICT')
                if 'drawing_ref' in part:
                    drawing = h.text(part['drawing_ref'])
                    if drawing_asset_reference(drawing):
                        asset = h.shape(requirement.get('drawing_asset'), ('request_ref', 'source', 'drawing_no', 'revision'))
                        h.require(asset['request_ref'] == drawing and asset['drawing_no'] == identity['drawing_no'] and
                                  asset['revision'] == identity['revision'], 'RFQ_DRAWING_ASSET_IDENTITY_CONFLICT')
                    else:
                        h.require(drawing == identity['drawing_no'], 'RFQ_DRAWING_CONFLICT')
            h.require(decisions.get('case_id') == case_id and decisions.get('request_sha256') == case['request']['sha256'] and
                      decisions.get('draft_sha256') == artifact['draft']['sha256'], 'DECISION_IDENTITY_MISMATCH')
            h.require(len(decisions['pricing_decisions']) == len(wanted) and
                      [d['line_id'] for d in decisions['pricing_decisions']] == [p['line_id'] for p in wanted], 'HIDDEN_OR_MISSING_PRICE_DECISION')
            semantic_hash = h.semantic_request_sha256(evidence.read(artifact['draft']), embedded=True)
            h.require(draft.get('provenance', {}).get('request_sha256') == semantic_hash, 'DRAFT_REQUEST_PROVENANCE_MISMATCH')
        criterion('identity', check_identity)
        def check_sources():
            for requirement, decision in zip(requirements['lines'], decisions['pricing_decisions']):
                target_case = target_cases[requirement['line_id']]
                current = h.bound_record(decision['supported_quote'], evidence)
                h.verify_financial_record(current, 'supported_current_quote', requirement['identity'], request['quote_date'], evidence)
                h.verify_financial_record(current, 'supported_current_quote', requirement['identity'], finish.date().isoformat(), evidence)
                domain = target_case['domains']['supported_current_quote']
                h.require(domain.get('state') == 'SOURCE_BOUND_INDEPENDENTLY_INSPECTABLE_RECORD' and domain.get('evidence') ==
                          decision['supported_quote'] and domain.get('record') == current, 'INDEPENDENT_CURRENT_ASSESSMENT_REQUIRED')
                source_records[requirement['line_id']] = current
                h.verify_identity(current['identity'], target_case['identity'])
        criterion('source_fitness', check_sources)
        def check_manufacturing():
            for part, requirement, decision in zip(request['parts'], requirements['lines'], decisions['pricing_decisions']):
                manufacturing = requirement['manufacturing']
                h.require(set(manufacturing) == {'material', 'finish', 'routing', 'tolerances'} and
                          decision.get('manufacturing_assumptions') == manufacturing == source_records[requirement['line_id']]['manufacturing'], 'MANUFACTURING_ASSUMPTION_MISMATCH')
                specification = h.bound_record(requirement['manufacturing_evidence'], evidence)
                h.require(specification.get('kind') == 'manufacturing_specification' and specification.get('manufacturing') == manufacturing and
                          h.timestamp(specification['recorded_at']).date().isoformat() <= request['quote_date'], 'MANUFACTURING_SPECIFICATION_REQUIRED')
                h.verify_identity(specification['identity'], requirement['identity'], full=True)
                for key in ('material', 'finish'):
                    if key in part:
                        h.require(part[key] == manufacturing[key], 'RFQ_MANUFACTURING_CONFLICT')
                if drawing_asset_reference(part.get('drawing_ref')):
                    asset = requirement['drawing_asset']
                    h.require(specification.get('drawing_asset') == asset and asset['request_ref'] == part['drawing_ref'] and
                              asset['drawing_no'] == requirement['identity']['drawing_no'] and
                              asset['revision'] == requirement['identity']['revision'], 'DRAWING_ASSET_NOT_BOUND_TO_SPECIFICATION')
                    h.require(evidence.read(asset['source']), 'DRAWING_ASSET_BYTES_REQUIRED')
                elif 'drawing_ref' in part:
                    h.require(part['drawing_ref'] == requirement['identity']['drawing_no'], 'RFQ_DRAWING_CONFLICT')
        criterion('manufacturing', check_manufacturing)
        def check_arithmetic():
            subtotal = Decimal(0)
            for line, requirement, decision in zip(draft['lines'], requirements['lines'], decisions['pricing_decisions']):
                price = h.number(line['unit_price'], True)
                h.require(price == h.number(decision['proposed_unit_price'], True) ==
                          h.number(source_records[requirement['line_id']]['amount']['unit_price'], True) and
                          decision.get('proposal_status') == 'NUMERIC_PROVISIONAL' and
                          h.number(line['extended_price'], True, 2) == h.extension(price, requirement['identity']['quantity']), 'UNIT_OR_EXTENSION_ARITHMETIC_MISMATCH')
                subtotal += h.number(line['extended_price'], True, 2)
            h.require(h.number(draft['priced_subtotal'], places=2) == h.number(draft['subtotal'], places=2) == subtotal, 'SUBTOTAL_ARITHMETIC_MISMATCH')
            charges = sum(h.number(v, places=2) for v in draft['charges'].values()) + sum(h.number(c['amount'], places=2) for c in draft['additional_charges'])
            h.require(h.number(draft['total'], True, 2) == subtotal + charges, 'TOTAL_ARITHMETIC_MISMATCH')
        criterion('cost_arithmetic', check_arithmetic)
        def check_terms():
            terms = requirements['terms']
            h.require(set(terms) == {'payment_terms', 'valid_until', 'lead_time_days', 'shipping', 'tax', 'additional_charges'}, 'FULL_TERMS_REQUIRED')
            h.text(terms['payment_terms'])
            h.require(h.iso_date(terms['valid_until']) >= request['quote_date'] and
                      h.number(terms['lead_time_days'], True, 0) > 0 and decisions.get('terms') == terms and
                      draft['charges'] == {k: terms[k] for k in ('shipping', 'tax')} and
                      draft['additional_charges'] == terms['additional_charges'] and
                      request.get('charges') == draft['charges'] and request.get('additional_charges', []) ==
                      draft['additional_charges'], 'TERMS_INCOMPLETE_OR_ALTERED')
            h.require(draft.get('state') == 'PRICED_REQUIRES_REVIEW' and draft.get('requires_human_review') is True and
                      draft.get('blockers') == [] and isinstance(decisions.get('uncertainties'), list) and
                      all(isinstance(v, str) and v.strip() for v in decisions['uncertainties']), 'PROVISIONAL_OR_BLOCKED_NOT_COMPLETED')
            h.require(status == 'COMPLETED', 'HELD_NOT_COMPLETED')
        criterion('completeness_terms', check_terms)
        def check_trace():
            h.require(trace.get('schema_version') == 1 and trace.get('kind') == 'quote_workflow_trace' and trace.get('attempt_id') == attempt_id and
                      trace.get('case_id') == case_id and trace.get('producer_id') == producer and
                      trace.get('request_sha256') == case['request']['sha256'] and isinstance(trace.get('events'), list) and trace['events'], 'TRACE_IDENTITY_MISMATCH')
            events = trace['events']
            h.require([e['ordinal'] for e in events] == list(range(1, len(events) + 1)), 'DROPPED_OR_REORDERED_TRACE_EVENT')
            allowed = {r['sha256'] for r in case['allowed_sources']}
            h.require(len(allowed) == len(case['allowed_sources']) and allowed and config['assessment']['sha256'] not in allowed, 'FROZEN_SOURCE_ALLOWLIST_INVALID')
            for ref in case['allowed_sources']:
                evidence.read(ref)
            read_hashes = set()
            prior = start
            for event in events:
                moment = h.timestamp(event['at'])
                h.require(prior <= moment <= finish and event.get('status') in ('OK', 'ERROR', 'TIMED_OUT'), 'TRACE_CHRONOLOGY_MISMATCH')
                prior = moment
                if event.get('kind') == 'source_read':
                    h.require(event.get('access') == 'read_only' and event.get('sources'), 'SOURCE_READ_EVIDENCE_REQUIRED')
                    for ref in event['sources']:
                        h.require(ref['sha256'] in allowed, 'UNFROZEN_OR_HIDDEN_SOURCE_READ')
                        evidence.read(ref)
                        read_hashes.add(ref['sha256'])
                elif event.get('kind') == 'draft_persisted':
                    proposal = evidence.json(event['artifact'])
                    h.require(proposal.get('request') == request and [p['line_id'] for p in proposal['lines']] ==
                              [p['line_id'] for p in requirements['lines']], 'TRACE_PROPOSAL_IDENTITY_MISMATCH')
                    for line, requirement in zip(proposal['lines'], requirements['lines']):
                        target_case = target_cases[requirement['line_id']]
                        invalid = False
                        try:
                            unit = None if line.get('unit_price') is None else h.number(line['unit_price'], True)
                        except ValueError:
                            unit, invalid = None, True
                        for basis in ('internal_calculation', 'recorded_customer_quote'):
                            domain = target_case['domains'][basis]
                            target = domain.get('unit_price') if domain.get('state') in ('VERIFIED_SOURCE_BYTES', 'VERIFIED_RECORDED_AMOUNT') else None
                            if basis == 'recorded_customer_quote' and not domain.get('target_comparable'):
                                target = None
                            quantity = h.number(requirement['identity']['quantity'], True, 0)
                            comparable = target is not None and quantity == h.number(target_case['identity']['quantity'], True, 0)
                            signed = None if unit is None or not comparable else unit - h.number(target, True)
                            numeric.append({'ordinal': event['ordinal'], 'line_id': line['line_id'], 'basis': basis,
                                            'proposal_state': proposal.get('state'), 'artifact_sha256': event['artifact']['sha256'],
                                            'numeric_state': 'INVALID' if invalid else 'MISSING' if unit is None else 'NUMERIC_PROVISIONAL',
                                            'unit_price': None if unit is None else str(unit), 'target': str(target) if comparable else None,
                                            'signed_unit_error': None if signed is None else str(signed),
                                            'absolute_unit_error': None if signed is None else str(abs(signed)),
                                            'signed_relative_error': None if signed is None else str(signed / h.number(target, True)),
                                            'signed_extension_error': None if signed is None else str(h.extension(unit, quantity) - h.extension(target, quantity))})
            h.require(any(e.get('kind') == 'draft_persisted' and e.get('artifact') == artifact['draft'] for e in events) and
                      any(e.get('kind') == 'price_decision_persisted' and e.get('artifact') == artifact['price_decisions'] for e in events), 'ACTUAL_FINAL_ARTIFACT_TRACE_MISSING')
            required_reads = {line['manufacturing_evidence']['source']['sha256'] for line in requirements['lines']}
            required_reads.update(line['drawing_asset']['source']['sha256'] for line in requirements['lines'] if 'drawing_asset' in line)
            for record in source_records.values():
                required_reads.update(c['evidence']['source']['sha256'] for c in record['costs'])
            h.require(required_reads <= read_hashes, 'MANUFACTURING_OR_COST_READ_TRACE_MISSING')
            if challenge['cohort'] == 'independent_live':
                for capability in ('read_only_polygres', 'arsumbris_typed_runtime'):
                    found = [e for e in events if e.get('capability') == capability and e.get('status') == 'OK']
                    h.require(found, 'LIVE_CAPABILITY_RECEIPT_MISSING')
                    for event in found:
                        runtime = h.bound_record(event['runtime_receipt'], evidence)
                        h.require(runtime.get('kind') == 'runtime_capability_receipt' and runtime.get('attempt_id') == attempt_id and
                                  runtime.get('capability') == capability and runtime.get('request_sha256') == case['request']['sha256'] and
                                  runtime.get('trace_event_ordinal') == event['ordinal'] and runtime.get('result_sha256') == event['result']['sha256'], 'LIVE_CAPABILITY_RECEIPT_MISMATCH')
                        evidence.read(event['result'])
        criterion('trace_integrity', check_trace)
        review = None
        def check_review():
            nonlocal review
            review = evidence.json(artifact['review'])
            review_receipt = h.bound_record(artifact['review_receipt'], evidence)
            h.require(review.get('kind') == 'independent_quote_review' and review.get('reviewer_id') == assignment['reviewer_id'] and
                      review.get('case_id') == case_id and review.get('attempt_id') == attempt_id and
                      review.get('assignment_sha256') == case['review_assignment']['source']['sha256'], 'FABRICATED_OR_SELF_REVIEW')
            h.require(review_receipt.get('kind') == 'independent_review_execution' and
                      review_receipt.get('reviewer_id') == assignment['reviewer_id'] and
                      review_receipt.get('review_sha256') == artifact['review']['sha256'] and
                      review_receipt.get('assignment_sha256') == case['review_assignment']['source']['sha256'] and
                      review_receipt.get('executor_id') == assignment['executor_id'] and
                      h.text(review_receipt.get('job_id')) and h.timestamp(review_receipt['started_at']) >= finish and
                      h.timestamp(review_receipt['finished_at']) >= h.timestamp(review_receipt['started_at']), 'INDEPENDENT_REVIEW_EXECUTION_NOT_BOUND')
            for key, expected in [('request', case['request']['sha256']), ('assessment', config['assessment']['sha256'])] + [
                    (key, artifact[key]['sha256']) for key in ('draft', 'price_decisions', 'trace')]:
                h.require(review.get(key + '_sha256') == expected and review_receipt.get(key + '_sha256') == expected, 'REVIEW_ARTIFACT_HASH_MISMATCH')
            criteria = review.get('criteria')
            required = set(CRITERIA) if cohort == 'eligible_quote' else {'safe_hold'}
            h.require(isinstance(criteria, list) and len(criteria) == len(required) and {c.get('id') for c in criteria} == required, 'INDEPENDENT_CRITERIA_MISSING_OR_DUPLICATE')
            for check in criteria:
                h.require(check.get('verdict') == 'PASS' and h.text(check.get('reason')) and
                          isinstance(check.get('source_findings'), list) and check['source_findings'], 'REVIEW_REJECTION_OR_UNSUPPORTED_NARRATIVE')
                for finding in check['source_findings']:
                    fact = h.bound_record(finding, evidence)
                    h.require(fact.get('kind') in ('supported_current_quote', 'manufacturing_specification', 'predeclared_quote_blocker'), 'REVIEW_FINDING_NOT_SOURCE_EVIDENCE')
                    h.require(fact.get('identity', {}).get('customer_id') == request['customer_id'] and
                              fact.get('identity', {}).get('part_no') in {p['identity']['part_no'] for p in requirements['lines']}, 'REVIEW_FINDING_IDENTITY_MISMATCH')
                    matches = [line for line in requirements['lines'] if line['identity']['part_no'] == fact['identity']['part_no']]
                    h.require(len(matches) == 1, 'REVIEW_FINDING_LINE_AMBIGUOUS')
                    h.verify_identity(fact['identity'], matches[0]['identity'], full=True)
                    if fact['kind'] == 'supported_current_quote':
                        h.verify_financial_record(fact, 'supported_current_quote', matches[0]['identity'], request['quote_date'], evidence)
                    elif fact['kind'] == 'manufacturing_specification':
                        h.require(fact.get('manufacturing') == matches[0]['manufacturing'] and
                                  h.timestamp(fact['recorded_at']).date().isoformat() <= request['quote_date'], 'REVIEW_FINDING_SPECIFICATION_MISMATCH')
                    else:
                        h.require(cohort == 'predeclared_blocked' and finding == case['blocked_evidence'] and
                                  h.timestamp(fact['adjudicated_at']) <= frozen_at, 'REVIEW_BLOCKER_NOT_PREDECLARED')
            expected_disposition = 'APPROVED_FOR_HUMAN_HANDOFF' if cohort == 'eligible_quote' else 'HELD'
            h.require(review.get('disposition') == expected_disposition, 'REVIEW_DISPOSITION_NOT_COMPLETED')
        criterion('independent_review', check_review)
        def check_handoff():
            handoff = h.bound_record(artifact['handoff'], evidence)
            executed_review = h.bound_record(artifact['review_receipt'], evidence)
            h.require(handoff.get('kind') == 'human_handoff_receipt' and handoff.get('reviewer_id') == assignment['reviewer_id'] and
                      handoff.get('case_id') == case_id and handoff.get('channel') == 'internal_private_review' and
                      h.timestamp(handoff['received_at']) >= h.timestamp(executed_review['finished_at']) >= finish and
                      h.timestamp(handoff['received_at']).date().isoformat() <= requirements['terms']['valid_until'] and
                      handoff.get('review_sha256') == artifact['review']['sha256'] and
                      handoff.get('draft_sha256') == artifact['draft']['sha256'] and handoff.get('request_sha256') == case['request']['sha256'], 'HUMAN_HANDOFF_NOT_SOURCE_BOUND')
            h.require(review is not None and review.get('disposition') == 'APPROVED_FOR_HUMAN_HANDOFF', 'HUMAN_HANDOFF_NOT_APPROVED')
        criterion('human_handoff', check_handoff)
        result['completed_quote_all_pass'] = cohort == 'eligible_quote' and all(v['pass'] for v in verdicts.values())
        if cohort == 'predeclared_blocked':
            try:
                blocker = h.bound_record(case['blocked_evidence'], evidence)
                h.require(blocker.get('kind') == 'predeclared_quote_blocker' and blocker.get('case_id') == case_id and
                          h.timestamp(blocker['adjudicated_at']) <= frozen_at and h.text(blocker.get('missing_fact')) and
                          status == 'HELD' and draft.get('state') == 'BLOCKED' and draft.get('requires_human_review') is True and
                          draft.get('total') is None and draft.get('blockers') and verdicts['identity']['pass'] and
                          verdicts['trace_integrity']['pass'] and verdicts['independent_review']['pass'], 'PREDECLARED_SAFE_HOLD_NOT_VERIFIED')
                result['safety_hold_all_pass'] = True
            except (ValueError, OSError, KeyError, TypeError, ArithmeticError):
                errors.append('PREDECLARED_SAFE_HOLD_NOT_VERIFIED')
    eligible = [r for r in results if r['cohort'] == 'eligible_quote']
    blocked = [r for r in results if r['cohort'] == 'predeclared_blocked']
    summary = {'frozen_cases': len(frozen), 'eligible_cases': sum(c['cohort'] == 'eligible_quote' for c in frozen),
               'all_retained_attempts': len(results), 'eligible_attempts': len(eligible),
               'attempt_states': dict(Counter(r['attempt_status'] for r in results)),
               'completed_quote_all_pass': sum(r['completed_quote_all_pass'] for r in eligible),
               'completed_quote_rate': sum(r['completed_quote_all_pass'] for r in eligible) / len(eligible) if eligible else None,
               'predeclared_blocked_attempts': len(blocked), 'safe_hold_all_pass': sum(r['safety_hold_all_pass'] for r in blocked),
               'undeclared_or_excluded_attempts': sum(r['cohort'] in ('undeclared', 'excluded') for r in results),
               'cohort': challenge['cohort'], 'live_90pct_goal': 'NOT_ESTABLISHED_REQUIRES_EXTERNAL_CONFIRMATION',
               'business_outperformance': 'NOT_ESTABLISHED', 'legacy_regression_tolerance': 'UNCHANGED_20_PERCENT'}
    numeric_summary = {}
    for basis in ('internal_calculation', 'recorded_customer_quote'):
        values = [Decimal(p['signed_relative_error']) for r in results for p in r['numeric_proposals']
                  if p['basis'] == basis and p['signed_relative_error'] is not None]
        average = sum(values) / len(values) if values else None
        variance = sum((v - average)**2 for v in values) / (len(values) - 1) if len(values) > 1 else None
        numeric_summary[basis] = {'comparable_proposals': len(values), 'mean_signed_relative_error': None if average is None else str(average),
                                 'mean_absolute_relative_error': str(sum(abs(v) for v in values) / len(values)) if values else None,
                                 'sample_variance_signed_relative_error': None if variance is None else str(variance)}
    summary['numeric_diagnostics_by_basis'] = numeric_summary
    report = {'schema_version': 1, 'kind': 'keller-completed-quote-decisions', 'challenge_sha256': config['challenge']['sha256'],
              'assessment_sha256': config['assessment']['sha256'], 'implementation_sha256': h.digest(Path(__file__).read_bytes()),
              'criteria': list(CRITERIA), 'summary': summary, 'attempts': results, 'inputs': evidence.inputs,
              'limits': 'Observed supplied artifacts are source-bound, not authenticated people, network executions or blind-cohort isolation. No synthetic/exposed score certifies the live goal; no safety hold lifts completion.'}
    return h.publish(config['out'], report, summary, evidence)
