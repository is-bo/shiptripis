/// Who receives the parcel.
///
/// The email here is not an address book entry — it is where the **delivery
/// code** is sent, and the traveller cannot complete the delivery without the
/// recipient reading that code back to them. A typo is therefore a stuck
/// delivery, not a cosmetic error, and the screen says so before the field
/// rather than after the failure.
///
/// The traveller never receives this email or phone at any point. That is the
/// server's rule; this screen simply never sends it anywhere else and never
/// logs it.
///
/// ## The recipient's language
///
/// The recipient has no ShipTrip account, so there is nobody to ask. The
/// sender picks, and the choice is theirs alone — the language is never
/// guessed from the recipient's name, their email address, its domain, or any
/// country the delivery touches. A new recipient starts on the sender's own
/// communication language because that is what the server would snapshot
/// anyway; an existing one starts on whatever is stored, so re-saving a
/// corrected phone number cannot quietly rewrite the language of an email
/// somebody is waiting for.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/account.dart';
import '../../domain/communication_language.dart';
import '../../domain/deal.dart';
import '../../l10n/app_localizations.dart';

class RecipientScreen extends ConsumerStatefulWidget {
  const RecipientScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<RecipientScreen> createState() => _RecipientScreenState();
}

class _RecipientScreenState extends ConsumerState<RecipientScreen> {
  static const _claimed = {
    'full_name',
    'email',
    'phone',
    'delivery_note',
    'communication_language',
  };

  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _note = TextEditingController();

  bool _busy = false;
  bool _prefilled = false;

  /// Null until the deal has loaded and the default is known. Nothing renders
  /// the selector before then, so it can never appear with no option chosen.
  CommunicationLanguage? _language;

  FieldErrorMap _errors = const FieldErrorMap.empty();

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _note.dispose();
    super.dispose();
  }

  /// Fills the form from the existing record exactly once, so an edit does not
  /// fight the user's typing on every rebuild.
  void _prefill(Deal deal, Account? sender) {
    if (_prefilled) return;
    final recipient = deal.recipient;

    if (recipient == null || !recipient.isFullRecord) {
      // No recipient yet. The sender's own stored preference is the default,
      // matching what the server snapshots when the field is omitted, and it
      // is a starting point rather than a decision — the row below is fully
      // editable before anything is saved.
      //
      // Stays unprefilled while the profile is still in flight, so the default
      // is the real preference rather than whatever happened to be readable
      // first.
      _language = sender?.preferredLanguage;
      _prefilled = _language != null;
      return;
    }

    _name.text = recipient.fullName ?? '';
    _email.text = recipient.email ?? '';
    _phone.text = recipient.phone ?? '';
    _note.text = recipient.deliveryNote ?? '';
    // Editing preserves what is stored. A deployment that predates the field
    // sends nothing, and English is the server's own fallback for that row —
    // the sender's preference is deliberately *not* used here, because
    // re-saving an address must not silently change the email's language.
    _language =
        recipient.communicationLanguage ?? CommunicationLanguage.fallback;
    _prefilled = true;
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _errors = const FieldErrorMap.empty();
    });

    final l = L.of(context);
    try {
      await ref
          .read(dealRepositoryProvider)
          .setRecipient(
            dealId: widget.dealId,
            fullName: _name.text,
            email: _email.text,
            phone: _phone.text,
            deliveryNote: _note.text,
            communicationLanguage: _language,
          );
      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(context, l.recipientSaved);
      context.pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _errors = FieldErrorMap.from(error));
      if (_errors.isEmpty) AppSnack.failure(context, error);
      if (error.code.impliesStaleClientState) refreshVolatileState(ref);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final validators = Validators.of(context);
    final deal = ref.watch(dealDetailProvider(widget.dealId));
    final sender = ref.watch(accountProvider);
    final unclaimed = _errors.unclaimed(_claimed);

    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.recipientTitle, showBack: true),
        body: AsyncView<Deal>(
          value: deal,
          onRetry: () => ref.invalidate(dealDetailProvider(widget.dealId)),
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpace.gutter),
            child: SkeletonDetail(),
          ),
          data: (data) {
            _prefill(data, sender);

            // The window is narrow and server-enforced: funded, and before the
            // parcel changes hands. Saying why is better than a dead form.
            final locked = data.pickupConfirmedAt != null;

            // Read after `_prefill`, which is what establishes it. Null only
            // while the profile has not landed; the selector is then omitted
            // rather than rendered with nothing chosen.
            final language = _language;

            return Form(
              key: _formKey,
              child: ListView(
                padding: AppScrollPadding.pageWithFooter(context),
                children: [
                  InfoNotice(
                    message: l.recipientExplainer,
                    tone: StatusTone.progress,
                    icon: Icons.mark_email_read_outlined,
                  ),
                  const SizedBox(height: AppSpace.lg),

                  if (locked) ...[
                    InfoNotice(
                      message: l.pickupConfirmedBody,
                      icon: Icons.lock_outline_rounded,
                    ),
                    const SizedBox(height: AppSpace.lg),
                  ],

                  if (unclaimed.isNotEmpty) ...[
                    InfoNotice(
                      message: unclaimed.join('\n'),
                      tone: StatusTone.bad,
                      icon: Icons.error_outline_rounded,
                    ),
                    const SizedBox(height: AppSpace.lg),
                  ],

                  AppTextField(
                    label: l.recipientName,
                    controller: _name,
                    isRequired: true,
                    enabled: !locked,
                    errorText: _errors['full_name'],
                    textCapitalization: TextCapitalization.words,
                    textInputAction: TextInputAction.next,
                    validator: validators.required,
                  ),
                  AppTextField(
                    label: l.recipientEmail,
                    controller: _email,
                    isRequired: true,
                    enabled: !locked,
                    errorText: _errors['email'],
                    helper: l.recipientEmailHelp,
                    keyboardType: TextInputType.emailAddress,
                    textInputAction: TextInputAction.next,
                    validator: validators.email,
                  ),

                  // Directly under the address it governs: this row decides
                  // what language arrives at that mailbox, not what language
                  // the sender is reading the app in.
                  if (language != null)
                    AppSegmentedChoice<CommunicationLanguage>(
                      label: l.recipientLanguage,
                      helper: l.recipientLanguageHelp,
                      errorText: _errors['communication_language'],
                      enabled: !locked,
                      selected: language,
                      onSelect: (value) => setState(() => _language = value),
                      options: [
                        for (final option in CommunicationLanguage.values)
                          AppChoice(value: option, label: option.nativeLabel),
                      ],
                    ),

                  AppTextField(
                    label: l.recipientPhone,
                    controller: _phone,
                    enabled: !locked,
                    errorText: _errors['phone'],
                    keyboardType: TextInputType.phone,
                    textInputAction: TextInputAction.next,
                  ),
                  AppTextField(
                    label: l.recipientNote,
                    controller: _note,
                    enabled: !locked,
                    errorText: _errors['delivery_note'],
                    maxLines: 3,
                    minLines: 2,
                    maxLength: 1000,
                    validator: (value) => validators.maxLength(value, 1000),
                  ),
                ],
              ),
            );
          },
        ),
        footer: deal.value?.pickupConfirmedAt != null
            ? null
            : AppButton(
                label: l.recipientSave,
                isLoading: _busy,
                onPressed: _submit,
              ),
      ),
    );
  }
}
