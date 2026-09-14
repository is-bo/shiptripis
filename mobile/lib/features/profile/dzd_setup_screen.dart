/// DZD payout profile (CCP / RIP) setup screen.
///
/// Implements the H6A contract:
/// - Strictly six inputs:
///   1. First name
///   2. Last name
///   3. CCP account number
///   4. CCP key (2 digits)
///   5. RIP (20 digits)
///   6. Crossed-cheque photo upload
/// - Absolutely NO NIP (national identification number) field.
/// - Mandated crossed cheque copy across EN/FR/AR.
/// - Clear notice that profile updates apply only to future payouts.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';

class DzdSetupScreen extends ConsumerStatefulWidget {
  const DzdSetupScreen({super.key});

  @override
  ConsumerState<DzdSetupScreen> createState() => _DzdSetupScreenState();
}

class _DzdSetupScreenState extends ConsumerState<DzdSetupScreen> {
  final _formKey = GlobalKey<FormState>();
  final _picker = ImagePicker();

  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _ccpNumberController = TextEditingController();
  final _ccpKeyController = TextEditingController();
  final _ripController = TextEditingController();

  XFile? _chequeFile;
  String? _chequeError;
  FieldErrorMap _fieldErrors = const FieldErrorMap.empty();
  bool _isSubmitting = false;

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _ccpNumberController.dispose();
    _ccpKeyController.dispose();
    _ripController.dispose();
    super.dispose();
  }

  Future<void> _pickImage(ImageSource source) async {
    try {
      final picked = await _picker.pickImage(
        source: source,
        maxWidth: 2400,
        maxHeight: 2400,
        imageQuality: 85,
      );
      if (picked != null && mounted) {
        setState(() {
          _chequeFile = picked;
          _chequeError = null;
        });
      }
    } on Object catch (e) {
      if (!mounted) return;
      AppSnack.failure(context, e);
    }
  }

  void _showImageSourceDialog() {
    final l = L.of(context);
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpace.lg,
            vertical: AppSpace.md,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.camera_alt_rounded),
                title: Text(l.dzdChequeAddPhoto),
                onTap: () {
                  Navigator.of(ctx).pop();
                  _pickImage(ImageSource.camera);
                },
              ),
              ListTile(
                leading: const Icon(Icons.photo_library_rounded),
                title: Text(l.dzdChequeAddPhoto),
                onTap: () {
                  Navigator.of(ctx).pop();
                  _pickImage(ImageSource.gallery);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _submit() async {
    if (_isSubmitting) return;

    final l = L.of(context);
    setState(() {
      _chequeError = null;
      _fieldErrors = const FieldErrorMap.empty();
    });

    final valid = _formKey.currentState?.validate() ?? false;
    if (_chequeFile == null) {
      setState(() => _chequeError = l.validationRequired);
      return;
    }
    if (!valid) return;

    setState(() => _isSubmitting = true);

    try {
      final repo = ref.read(paymentRepositoryProvider);

      // 1. Upload cheque proof image to obtain server reference.
      final fileName = _chequeFile!.name.isNotEmpty
          ? _chequeFile!.name
          : 'cheque_barre.jpg';
      final proofRef = await repo.uploadPayoutProof(
        filePath: _chequeFile!.path,
        fileName: fileName,
      );

      // 2. Resolve expected revision from current profile summary if any.
      final summary = await repo.payoutMethods();
      final expectedRev = summary.revisionFor('DZD');

      // 3. Submit profile with exactly 6 product values.
      await repo.submitDzdProfile(
        expectedRevision: expectedRev,
        firstName: _firstNameController.text.trim(),
        lastName: _lastNameController.text.trim(),
        ccpNumber: _ccpNumberController.text.trim(),
        ccpKey: _ccpKeyController.text.trim(),
        rip: _ripController.text.trim(),
        proofReference: proofRef,
      );

      if (!mounted) return;
      ref.invalidate(payoutMethodsProvider);
      AppSnack.success(context, l.dzdSubmitSuccess);
      Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _fieldErrors = FieldErrorMap.from(e));
      AppSnack.failure(context, e);
    } on Object catch (e) {
      if (!mounted) return;
      AppSnack.failure(context, e);
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return AppScaffold(
      topBar: AppTopBar(title: l.dzdFormTitle, showBack: true),
      body: Form(
        key: _formKey,
        child: SingleChildScrollView(
          padding: AppScrollPadding.page(context),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Future-scope notice: does not retroactively mutate in-flight payouts.
              InfoNotice(
                title: l.payoutPreferenceScopeNote,
                message: l.dzdFormScopeExplainer,
                tone: StatusTone.waiting,
                icon: Icons.info_outline_rounded,
              ),
              const SizedBox(height: AppSpace.xl),

              // Account holder identity
              AppTextField(
                label: l.dzdFirstNameLabel,
                controller: _firstNameController,
                isRequired: true,
                errorText: _fieldErrors['first_name'],
                textCapitalization: TextCapitalization.words,
                validator: (v) => (v == null || v.trim().isEmpty)
                    ? l.validationRequired
                    : null,
              ),
              const SizedBox(height: AppSpace.lg),

              AppTextField(
                label: l.dzdLastNameLabel,
                controller: _lastNameController,
                isRequired: true,
                errorText: _fieldErrors['last_name'],
                textCapitalization: TextCapitalization.words,
                validator: (v) => (v == null || v.trim().isEmpty)
                    ? l.validationRequired
                    : null,
              ),
              const SizedBox(height: AppSpace.xl),

              // Postal account details
              AppTextField(
                label: l.dzdCcpNumberLabel,
                controller: _ccpNumberController,
                hint: l.dzdCcpNumberHint,
                isRequired: true,
                errorText: _fieldErrors['ccp_number'],
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                validator: (v) {
                  if (v == null || v.trim().isEmpty) {
                    return l.validationRequired;
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppSpace.lg),

              AppTextField(
                label: l.dzdCcpKeyLabel,
                controller: _ccpKeyController,
                hint: l.dzdCcpKeyHint,
                isRequired: true,
                errorText: _fieldErrors['ccp_key'],
                keyboardType: TextInputType.number,
                maxLength: 2,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(2),
                ],
                validator: (v) {
                  if (v == null || v.trim().isEmpty) {
                    return l.validationRequired;
                  }
                  if (v.trim().length != 2) {
                    return l.validationRequired;
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppSpace.lg),

              AppTextField(
                label: l.dzdRipLabel,
                controller: _ripController,
                hint: l.dzdRipHint,
                isRequired: true,
                errorText: _fieldErrors['rip'],
                keyboardType: TextInputType.number,
                maxLength: 20,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(20),
                ],
                validator: (v) {
                  if (v == null || v.trim().isEmpty) {
                    return l.validationRequired;
                  }
                  if (v.trim().length != 20) {
                    return l.validationRequired;
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppSpace.xl),

              // Mandated Cheque Image Section
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(
                          Icons.document_scanner_outlined,
                          size: 20,
                          color: c.brand,
                        ),
                        const SizedBox(width: AppSpace.sm),
                        Expanded(
                          child: Text(
                            l.dzdChequeProofLabel,
                            style: text.titleSmall?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpace.xs),
                    Text(
                      l.dzdChequeProofHelper,
                      style: text.bodySmall?.copyWith(color: c.textSecondary),
                    ),
                    const SizedBox(height: AppSpace.md),

                    if (_chequeFile != null) ...[
                      ClipRRect(
                        borderRadius: BorderRadius.circular(12),
                        child: Image.file(
                          File(_chequeFile!.path),
                          height: 180,
                          width: double.infinity,
                          fit: BoxFit.cover,
                          errorBuilder: (_, _, _) => Container(
                            height: 120,
                            color: c.surfaceSunken,
                            alignment: Alignment.center,
                            child: Icon(
                              Icons.broken_image_rounded,
                              color: c.textTertiary,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: AppSpace.sm),
                      Align(
                        alignment: Alignment.centerRight,
                        child: TextButton.icon(
                          onPressed: _isSubmitting
                              ? null
                              : _showImageSourceDialog,
                          icon: const Icon(Icons.edit_rounded, size: 16),
                          label: Text(l.dzdChequeReplacePhoto),
                        ),
                      ),
                    ] else ...[
                      OutlinedButton.icon(
                        onPressed: _isSubmitting
                            ? null
                            : _showImageSourceDialog,
                        icon: const Icon(Icons.add_a_photo_outlined),
                        label: Text(l.dzdChequeAddPhoto),
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size(double.infinity, 52),
                        ),
                      ),
                    ],

                    if (_chequeError != null) ...[
                      const SizedBox(height: AppSpace.sm),
                      Text(
                        _chequeError!,
                        style: text.bodySmall?.copyWith(color: c.danger),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: AppSpace.xxl),

              AppButton(
                label: l.dzdSubmitAction,
                variant: AppButtonVariant.primary,
                icon: Icons.check_circle_outline_rounded,
                isLoading: _isSubmitting,
                onPressed: _isSubmitting ? null : _submit,
              ),
              const SizedBox(height: AppSpace.xxl),
            ],
          ),
        ),
      ),
    );
  }
}
