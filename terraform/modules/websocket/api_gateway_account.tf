# API Gateway account-level CloudWatch Logs role
# This is a one-time setup per AWS account/region.
# Set var.manage_api_gateway_account = true to create the role and configure the account.
# Set to false if another team/stack already manages this in your account.

data "aws_iam_policy_document" "api_gateway_logs_assume_role" {
  count = var.manage_api_gateway_account ? 1 : 0

  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["apigateway.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "api_gateway_cloudwatch" {
  count              = var.manage_api_gateway_account ? 1 : 0
  name               = "${var.project_name}-apigw-cloudwatch-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.api_gateway_logs_assume_role[0].json
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  count      = var.manage_api_gateway_account ? 1 : 0
  role       = aws_iam_role.api_gateway_cloudwatch[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "main" {
  count               = var.manage_api_gateway_account ? 1 : 0
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch[0].arn
}
