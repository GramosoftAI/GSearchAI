// import { Input, Typography } from "antd";
// import { Controller } from "react-hook-form";
// import styles from "../../features/auth/style/RegisterForm.module.css";

// const { Text } = Typography;

// interface Props {
//   name: any;
//   control: any;
//   label: string;
//   error?: string;
//   type?: string;
//   prefix?: React.ReactNode;
//   isPassword?: boolean;
// }

// export default function FormField({
//   name,
//   control,
//   label,
//   error,
//   prefix,
//   isPassword,
// }: Props) {
//   return (
//     <div>
//       <Text className={styles.label}>
//         {label} <span className={styles.required}>*</span>
//       </Text>

//       <Controller
//         name={name}
//         control={control}
//         render={({ field }) => (
//           <>
//             {isPassword ? (
//               <Input.Password
//                 {...field}
//                 prefix={prefix}
//                 className={styles.input}
//               />
//             ) : (
//               <Input {...field} prefix={prefix} className={styles.input} />
//             )}

//             {error && <Text className={styles.error}>{error}</Text>}
//           </>
//         )}
//       />
//     </div>
//   );
// }