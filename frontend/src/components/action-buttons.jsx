import { useI18n } from '../i18n-context.jsx';

export function DeleteButton({ onClick, disabled, deleting, small = true, label }) {
  const { t } = useI18n();
  return (
    <button
      class={`btn btn-danger ${small ? 'btn-small' : ''}`}
      onClick={onClick}
      disabled={disabled || deleting}
    >
      {deleting ? t('common.deleting') : label || t('common.delete')}
    </button>
  );
}

export function EditButton({ onClick, active, small = true }) {
  const { t } = useI18n();
  return (
    <button
      class={`btn btn-secondary ${small ? 'btn-small' : ''}`}
      onClick={onClick}
    >
      {active ? t('common.close') : t('common.edit')}
    </button>
  );
}

export function SaveButton({ onClick, disabled, saving, small = true }) {
  const { t } = useI18n();
  return (
    <button
      class={`btn btn-primary ${small ? 'btn-small' : ''}`}
      onClick={onClick}
      disabled={disabled || saving}
    >
      {saving ? t('common.saving') : t('common.save')}
    </button>
  );
}

export function CancelButton({ onClick, small = true }) {
  const { t } = useI18n();
  return (
    <button class={`btn btn-secondary ${small ? 'btn-small' : ''}`} onClick={onClick}>
      {t('common.cancel')}
    </button>
  );
}
