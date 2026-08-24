resource "oci_ons_notification_topic" "operations" {
  compartment_id = var.compartment_ocid
  name           = "z1rr-racetime-operations"
  description    = "Secret-free Z1RR RaceTime infrastructure notifications"
  freeform_tags  = local.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_ons_subscription" "alert_relay" {
  for_each = var.alert_relay_endpoint == null ? {} : {
    primary = var.alert_relay_endpoint
  }

  compartment_id = var.compartment_ocid
  endpoint       = each.value
  protocol       = "CUSTOM_HTTPS"
  topic_id       = oci_ons_notification_topic.operations.id
}

resource "oci_ons_subscription" "email_fallback" {
  for_each = var.fallback_email_endpoint == null ? {} : {
    fallback = var.fallback_email_endpoint
  }

  compartment_id = var.compartment_ocid
  endpoint       = each.value
  protocol       = "EMAIL"
  topic_id       = oci_ons_notification_topic.operations.id
}

locals {
  alarm_common = {
    compartment_id        = var.compartment_ocid
    destinations          = [oci_ons_notification_topic.operations.id]
    is_enabled            = true
    metric_compartment_id = var.compartment_ocid
  }
}

# Task 9 emits A1ForecastWarning only when the accepted forecast is below
# 2,650 and projected usage exceeds max(100 hours, 5%) or its 72-hour slope.
# When forecast >= 2650, forecast acceptance is the warning and this warning is suppressed.
resource "oci_monitoring_alarm" "a1_forecast_warning" {
  compartment_id               = local.alarm_common.compartment_id
  destinations                 = local.alarm_common.destinations
  display_name                 = "Z1RR RaceTime A1 allowance forecast warning"
  is_enabled                   = local.alarm_common.is_enabled
  metric_compartment_id        = local.alarm_common.metric_compartment_id
  namespace                    = "z1rr_racetime"
  query                        = "A1ForecastWarning[1h].max() > 0"
  severity                     = "WARNING"
  pending_duration             = "PT1M"
  repeat_notification_duration = "PT6H"
  body                         = "Allowance-utilization signal at zero possible spend. Check Restream sleep automation, encoders, and control planes; then reconcile the dated forecast."
}

resource "oci_monitoring_alarm" "a1_allowance_escalation" {
  compartment_id               = local.alarm_common.compartment_id
  destinations                 = local.alarm_common.destinations
  display_name                 = "Z1RR tenancy A1 allowance escalation"
  is_enabled                   = local.alarm_common.is_enabled
  metric_compartment_id        = local.alarm_common.metric_compartment_id
  namespace                    = "z1rr_racetime"
  query                        = "A1ProjectedMonthEndOCPUHours[1h].max() > 2900"
  severity                     = "CRITICAL"
  pending_duration             = "PT1M"
  repeat_notification_duration = "PT3H"
  body                         = "Actual or projected A1 usage crossed 2,900 hours. Check Restream sleep automation first, then record expected overage and cost."
}

resource "oci_monitoring_alarm" "retained_volume_cost_warning" {
  compartment_id               = local.alarm_common.compartment_id
  destinations                 = local.alarm_common.destinations
  display_name                 = "Z1RR retained boot-volume cost warning"
  is_enabled                   = local.alarm_common.is_enabled
  metric_compartment_id        = local.alarm_common.metric_compartment_id
  namespace                    = "z1rr_racetime"
  query                        = "RetainedBootVolumeMonthlyCostUSD[1h].max() > 4.61"
  severity                     = "WARNING"
  pending_duration             = "PT1M"
  repeat_notification_duration = "PT12H"
  body                         = "Retained boot-volume forecast is more than $1 above the $3.61 baseline; reconcile inventory and forecast."
}

resource "oci_monitoring_alarm" "retained_volume_cost_escalation" {
  compartment_id               = local.alarm_common.compartment_id
  destinations                 = local.alarm_common.destinations
  display_name                 = "Z1RR retained boot-volume cost escalation"
  is_enabled                   = local.alarm_common.is_enabled
  metric_compartment_id        = local.alarm_common.metric_compartment_id
  namespace                    = "z1rr_racetime"
  query                        = "RetainedBootVolumeMonthlyCostUSD[1h].max() > 6.61"
  severity                     = "CRITICAL"
  pending_duration             = "PT1M"
  repeat_notification_duration = "PT6H"
  body                         = "Retained boot-volume forecast is more than $3 above baseline; reconcile volume inventory and ownership."
}

resource "oci_monitoring_alarm" "object_storage_warning" {
  compartment_id               = local.alarm_common.compartment_id
  destinations                 = local.alarm_common.destinations
  display_name                 = "Z1RR Object Storage entitlement warning"
  is_enabled                   = local.alarm_common.is_enabled
  metric_compartment_id        = local.alarm_common.metric_compartment_id
  namespace                    = "z1rr_racetime"
  query                        = "ObjectStorageEntitlementUtilizationPercent[1h].max() > 75"
  severity                     = "WARNING"
  pending_duration             = "PT1M"
  repeat_notification_duration = "PT12H"
  body                         = "Verified Object Storage byte or request entitlement exceeded 75 percent; reconcile backup growth and retention."
}

resource "oci_monitoring_alarm" "object_storage_escalation" {
  compartment_id               = local.alarm_common.compartment_id
  destinations                 = local.alarm_common.destinations
  display_name                 = "Z1RR Object Storage entitlement escalation"
  is_enabled                   = local.alarm_common.is_enabled
  metric_compartment_id        = local.alarm_common.metric_compartment_id
  namespace                    = "z1rr_racetime"
  query                        = "ObjectStorageEntitlementUtilizationPercent[1h].max() > 90"
  severity                     = "CRITICAL"
  pending_duration             = "PT1M"
  repeat_notification_duration = "PT6H"
  body                         = "Verified Object Storage byte or request entitlement exceeded 90 percent; reconcile backup growth and retention now."
}

resource "oci_monitoring_alarm" "instance_cpu" {
  compartment_id               = local.alarm_common.compartment_id
  destinations                 = local.alarm_common.destinations
  display_name                 = "Z1RR RaceTime sustained CPU"
  is_enabled                   = local.alarm_common.is_enabled
  metric_compartment_id        = local.alarm_common.metric_compartment_id
  namespace                    = "oci_computeagent"
  query                        = "CpuUtilization[5m]{resourceId=\"${oci_core_instance.racetime.id}\"}.mean() > 80"
  severity                     = "WARNING"
  pending_duration             = "PT15M"
  repeat_notification_duration = "PT6H"
  body                         = "RaceTime CPU exceeded the documented 20 percent burst-headroom boundary; inspect room load and run the performance gate."
}
